"""Freeze the FLEURS subset, replay audio and collect XTurnix traces.

``prepare-data`` and ``verify-data`` belong to XTX-001. ``replay`` belongs to
XTX-003: it streams the frozen audio in real time through Nemotron and XTurnix
and records causal events. It deliberately computes no latency or WER metric;
XTX-004 owns offline scoring.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

FLEURS_REPO = "google/fleurs"
FLEURS_REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
TEST_COUNT = 100
DEV_COUNT = 1
EXPECTED_TEST_DURATION_SECONDS = 969.26
EXPECTED_TEST_NORMALIZED_WORDS = 2162
EXPECTED_TEST_FIRST_FILE = "2074231104398719826.wav"
EXPECTED_TEST_LAST_FILE = "1277588711703410007.wav"
EXPECTED_DEV_FILE = "786465049904960526.wav"
NORMALIZER_PACKAGE = "whisper-normalizer"
NORMALIZER_VERSION = "0.1.12"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"
DEFAULT_MIN_FREE_GIB = 30
DEFAULT_ASSET_LIMIT_GIB = 10
DOWNLOAD_CONCURRENCY = 1

MANIFEST_SCHEMA = "xtx-001-fleurs-manifest-v1"
LOCK_SCHEMA = "xtx-001-fleurs-lock-v1"
BASELINE_SCHEMA = "xtx-001-historical-asr-baseline-v1"
REPORT_SCHEMA = "xtx-001-fleurs-prepare-report-v1"
VERIFICATION_SCHEMA = "xtx-001-fleurs-verification-v1"
REPLAY_CONFIG_SCHEMA = "xtx-002-xturnix-fleurs-config-v1"
INPUT_SNAPSHOT_SCHEMA = "xtx-003-input-snapshot-v1"
REPLAY_STATUS_SCHEMA = "xtx-003-replay-status-v1"
REPLAY_REPORT_SCHEMA = "xtx-003-replay-report-v1"
TRACE_SCHEMA = "xtx-003-replay-trace-v1"
SILENCE_PACKET = b"\x00\x00"
TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
TRACE_LIMIT_BYTES = 2 * 1024**3

BASELINE_COMMIT = "f6ad9d9ba04e4e046dcfcdd480b5343165466046"
BASELINE_REPORT = (
    f"https://github.com/Vitalrubbish/InterClarify/blob/{BASELINE_COMMIT}/"
    "docs/asr_selection_report.md"
)
BASELINE_RESULTS = (
    f"https://github.com/Vitalrubbish/InterClarify/blob/{BASELINE_COMMIT}/"
    "reports/asr_selection/20261016-results/component_repeated.json"
)

SPLITS = (("test", TEST_COUNT), ("dev", DEV_COUNT))


@dataclass(frozen=True)
class Expectations:
    """Frozen totals and boundary files that a restored subset must reproduce."""

    test_count: int = TEST_COUNT
    dev_count: int = DEV_COUNT
    test_duration_seconds: float = EXPECTED_TEST_DURATION_SECONDS
    test_normalized_words: int = EXPECTED_TEST_NORMALIZED_WORDS
    first_file: str = EXPECTED_TEST_FIRST_FILE
    last_file: str = EXPECTED_TEST_LAST_FILE
    dev_file: str = EXPECTED_DEV_FILE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def selection_hash(filename: str) -> str:
    """Reproduce the historical SHA256(filename) ascending selection rule."""
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def read_tsv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        raise ValueError(f"Empty FLEURS TSV: {path}")
    for index, row in enumerate(rows, 1):
        if len(row) != 7:
            raise ValueError(f"{path}:{index}: expected 7 columns, found {len(row)}")
        filename = row[1]
        if not filename or Path(filename).name != filename:
            raise ValueError(f"{path}:{index}: invalid audio filename {filename!r}")
        if not row[2].strip() or not row[3].strip():
            raise ValueError(f"{path}:{index}: missing reference text")
    return rows


def select_rows(rows: Iterable[list[str]], count: int) -> list[tuple[str, list[str]]]:
    """Select rows by ascending SHA256(filename), retaining the selection key."""
    ranked = sorted(((selection_hash(row[1]), row) for row in rows), key=lambda item: item[0])
    if len(ranked) < count:
        raise ValueError(f"Requested {count} rows but only {len(ranked)} are available")
    return ranked[:count]


def load_english_normalizer() -> Callable[[str], str]:
    """Load exactly whisper-normalizer 0.1.12 used by the historical totals."""
    try:
        version = importlib.metadata.version(NORMALIZER_PACKAGE)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(
            f"{NORMALIZER_PACKAGE}=={NORMALIZER_VERSION} is required to count "
            "normalized reference words"
        ) from error
    if version != NORMALIZER_VERSION:
        raise RuntimeError(
            f"{NORMALIZER_PACKAGE} {version} is installed; the frozen subset uses "
            f"{NORMALIZER_VERSION}. Install the pinned version instead of mixing counts."
        )
    from whisper_normalizer.english import EnglishTextNormalizer

    return EnglishTextNormalizer()


def count_words(normalizer: Callable[[str], str], text: str) -> int:
    return len(normalizer(text).split())


def historical_baseline() -> dict[str, object]:
    """Return the immutable historical Nemotron latency record used by XTX-004."""
    measurable = 3068
    reference = 4324
    return {
        "schema": BASELINE_SCHEMA,
        "source_commit": BASELINE_COMMIT,
        "sources": {"selection_report": BASELINE_REPORT, "repeated_results": BASELINE_RESULTS},
        "results_path": "component_repeated.json",
        "model": "nvidia/nemotron-speech-streaming-en-0.6b",
        "configuration": "EN160",
        "statistic": "estimated_word_latency_seconds",
        "definition": (
            "First delivery time of a correctly transcribed, alignable reference word "
            "minus the independent CTC-estimated reference word end time."
        ),
        "valid_repeats": 2,
        "unique_recordings": 100,
        "sample_runs": 200,
        "reference_words": reference,
        "measurable_words": measurable,
        "measurable_coverage": measurable / reference,
        "p50_seconds": 0.41358285225927827,
        "p95_seconds": 1.0326687976904216,
        "p50_ms": 413.58285225927827,
        "p95_ms": 1032.6687976904216,
        "wer": 0.07678075855689177,
        "usage": (
            "413.582852 ms is a per-word P50 constant, not a mean, not a last-word "
            "measurement and not an end-to-end result. It may only be added to the "
            "measured control increment and must be reported as estimated."
        ),
        "limitations": [
            "Only 3068 of 4324 reference words were correct and alignable; missing words are not filled with zero.",
            "The two historical repeats reuse the same 100 recordings and do not form 200 independent samples.",
            "Runtime, polling and GPU sharing differed from the XTurnix run; the combined value is an estimate.",
        ],
    }


class DatasetPreparer:
    """Download or reuse, select, freeze and verify the 100 test + 1 dev recordings."""

    def __init__(
        self,
        root: Path,
        endpoint: str = DEFAULT_HF_ENDPOINT,
        expected: Expectations = Expectations(),
        min_free_gib: int = DEFAULT_MIN_FREE_GIB,
        asset_limit_gib: int = DEFAULT_ASSET_LIMIT_GIB,
        reuse_dir: Path | None = None,
        overwrite: bool = False,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.endpoint = endpoint.rstrip("/")
        self.expected = expected
        self.min_free_bytes = min_free_gib * 1024**3
        self.asset_limit_bytes = asset_limit_gib * 1024**3
        self.reuse_dir = reuse_dir.expanduser().resolve() if reuse_dir else None
        self.overwrite = overwrite
        self.data_dir = self.root / "dataset" / "fleurs_en_us"
        self.source_dir = self.data_dir / "source" / "en_us"
        self.events_path = self.data_dir / "prepare_events.jsonl"
        self.lock_path = self.data_dir / "dataset.lock.json"
        self.manifest_path = self.data_dir / "manifest.json"
        self.baseline_path = self.data_dir / "historical_asr_baseline.json"
        self.report_path = self.data_dir / "prepare_report.json"
        self.normalizer: Callable[[str], str] | None = None
        self.started = time.monotonic()
        self.source_mode = "reuse" if self.reuse_dir else "download"
        self.sources: dict[str, dict[str, object]] = {}
        self.source_copies: dict[str, dict[str, object]] = {}
        self.samples: list[dict[str, object]] = []
        self.downloaded_bytes = 0

    def event(self, name: str, **fields: object) -> None:
        record = {"time": utc_now(), "event": name, **fields}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{name}] " + json.dumps(fields, ensure_ascii=False), flush=True)

    def disk_stats(self) -> dict[str, int]:
        probe = self.data_dir if self.data_dir.exists() else self.root
        usage = shutil.disk_usage(probe)
        return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}

    def directory_bytes(self, path: Path) -> int:
        if not path.exists():
            return 0
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    def check_capacity(self) -> dict[str, int]:
        stats = self.disk_stats()
        if stats["free_bytes"] < self.min_free_bytes:
            raise RuntimeError(
                f"Only {stats['free_bytes'] / 1024**3:.1f} GiB free under {self.root}; "
                f"at least {self.min_free_bytes / 1024**3:.0f} GiB must be available"
            )
        return stats

    def reset_data_dir(self) -> None:
        """Replace a previous freeze only when --overwrite was requested."""
        if self.data_dir.exists() and any(self.data_dir.iterdir()):
            if not self.overwrite:
                raise RuntimeError(
                    f"{self.data_dir} already exists; pass --overwrite to replace the freeze"
                )
            shutil.rmtree(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch_source(self, relative: str) -> Path:
        """Fetch one pinned dataset file and record its immutable identity."""
        from huggingface_hub import hf_hub_download

        started = time.monotonic()
        self.event("download_start", file=relative, revision=FLEURS_REVISION)
        path = Path(
            hf_hub_download(
                repo_id=FLEURS_REPO,
                filename=relative,
                repo_type="dataset",
                revision=FLEURS_REVISION,
                endpoint=self.endpoint,
            )
        )
        digest = sha256_file(path)
        self.sources[relative] = {
            "origin": "hf_hub_download",
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": digest,
            "revision": FLEURS_REVISION,
        }
        self.downloaded_bytes += path.stat().st_size
        self.event(
            "download_complete",
            file=relative,
            bytes=path.stat().st_size,
            sha256=digest,
            seconds=round(time.monotonic() - started, 3),
        )
        return path

    def download_sources(self) -> dict[str, Path]:
        sources = {}
        for relative in (
            "data/en_us/test.tsv",
            "data/en_us/dev.tsv",
            "data/en_us/audio/test.tar.gz",
            "data/en_us/audio/dev.tar.gz",
        ):
            sources[relative] = self.fetch_source(relative)
        return sources

    def resolve_reuse_dataset(self) -> Path:
        """Accept either a dataset directory or a workspace root from an earlier run."""
        if self.reuse_dir is None:
            raise RuntimeError("Reuse mode requires --reuse-dir")
        candidates = [self.reuse_dir, self.reuse_dir / "dataset" / "fleurs_en_us"]
        for candidate in candidates:
            if (candidate / "source" / "en_us" / "test.tsv").is_file():
                return candidate
        raise ValueError(
            f"{self.reuse_dir} has no source/en_us/test.tsv; point --reuse-dir at a "
            "FLEURS dataset directory or its workspace root"
        )

    def stage_reused_sources(self) -> dict[str, Path]:
        """Copy the small TSVs from an existing read-only dataset."""
        reuse = self.resolve_reuse_dataset()
        if reuse.resolve() == self.data_dir.resolve():
            raise ValueError("--reuse-dir must differ from the target dataset directory")
        sources = {}
        for split, _ in SPLITS:
            relative = f"data/en_us/{split}.tsv"
            path = reuse / "source" / "en_us" / f"{split}.tsv"
            sources[relative] = path
            self.sources[relative] = {
                "origin": "reused",
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "revision": FLEURS_REVISION,
            }
        self.event(
            "reuse_source_complete",
            reuse_dir=str(reuse),
            old_manifest_used=False,
            note="Only TSVs and selected WAV bytes are reused; all hashes are recomputed.",
        )
        return sources

    def copy_source(self, relative: str, path: Path) -> None:
        """Keep the small TSV files beside the manifest for offline auditing."""
        destination = self.source_dir / Path(relative).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        digest = sha256_file(destination)
        if digest != self.sources[relative]["sha256"]:
            raise RuntimeError(f"Copied source changed: {relative}")
        self.source_copies[relative] = {
            "relative_path": str(destination.relative_to(self.data_dir)),
            "bytes": destination.stat().st_size,
            "sha256": digest,
        }

    def select_sources(self, sources: dict[str, Path]) -> dict[str, list[tuple[str, list[str]]]]:
        limits = {"test": self.expected.test_count, "dev": self.expected.dev_count}
        selected = {}
        for split, _ in SPLITS:
            rows = read_tsv(sources[f"data/en_us/{split}.tsv"])
            selected[split] = select_rows(rows, limits[split])
            self.event(
                "selection_complete",
                split=split,
                available=len(rows),
                selected=len(selected[split]),
                rule="SHA256(filename) ascending",
                first_file=selected[split][0][1][1],
                last_file=selected[split][-1][1][1],
            )
        test_names = {row[1] for _, row in selected["test"]}
        dev_names = {row[1] for _, row in selected["dev"]}
        if test_names & dev_names:
            raise ValueError("A recording was selected for both test and dev")
        return selected

    def copy_reused_audio(
        self, selected: dict[str, list[tuple[str, list[str]]]]
    ) -> None:
        """Copy only selected WAV bytes from the reused dataset without transforming them."""
        reuse = self.resolve_reuse_dataset()
        for split, _ in SPLITS:
            source_audio = reuse / "audio" / split
            wanted = {row[1] for _, row in selected[split]}
            actual = {path.name for path in source_audio.glob("*.wav")}
            if actual != wanted:
                missing = sorted(wanted - actual)
                extra = sorted(actual - wanted)
                raise ValueError(
                    f"Reused audio/{split} differs from the frozen selection; "
                    f"missing={missing[:3]} extra={extra[:3]}"
                )
            destination_dir = self.data_dir / "audio" / split
            destination_dir.mkdir(parents=True, exist_ok=True)
            for filename in sorted(wanted):
                temporary = destination_dir / (filename + ".part")
                shutil.copyfile(source_audio / filename, temporary)
                os.replace(temporary, destination_dir / filename)
            self.event("reuse_audio_complete", split=split, members=len(wanted))
        self.event(
            "reuse_complete",
            reuse_dir=str(reuse),
            old_manifest_used=False,
            note="Selection was rebuilt from the pinned TSVs; copies are re-hashed later.",
        )

    def extract(self, split: str, archive_path: Path, selected: list[tuple[str, list[str]]]) -> None:
        """Extract only the selected WAV members without transforming audio."""
        audio_dir = self.data_dir / "audio" / split
        audio_dir.mkdir(parents=True, exist_ok=True)
        wanted = {row[1]: row for _, row in selected}
        extracted = set()
        with tarfile.open(archive_path) as archive:
            members = {
                Path(member.name).name: member
                for member in archive.getmembers()
                if member.isfile()
            }
            for filename in wanted:
                if filename not in members:
                    raise ValueError(f"{split}: archive lacks selected member {filename}")
                temporary = audio_dir / (filename + ".part")
                with archive.extractfile(members[filename]) as source:
                    if source is None:
                        raise ValueError(f"{split}: cannot read archive member {filename}")
                    with temporary.open("wb") as target:
                        shutil.copyfileobj(source, target)
                os.replace(temporary, audio_dir / filename)
                extracted.add(filename)
        if extracted != set(wanted):
            raise RuntimeError(f"{split}: extracted member set differs from selection")
        stale = [path for path in audio_dir.glob("*.wav") if path.name not in wanted]
        for path in stale:
            path.unlink()
        self.event(
            "extract_complete",
            split=split,
            members=len(extracted),
            removed_stale=len(stale),
            archive=str(archive_path),
        )

    def build_sample(self, split: str, selection_key: str, row: list[str]) -> dict[str, object]:
        import soundfile as sf

        if self.normalizer is None:
            raise RuntimeError("English normalizer must be loaded before building the manifest")
        filename = row[1]
        audio_path = self.data_dir / "audio" / split / filename
        info = sf.info(str(audio_path))
        normalized = self.normalizer(row[2])
        return {
            "sample_id": f"{split}/{filename}",
            "split": split,
            "relative_path": str(audio_path.relative_to(self.data_dir)),
            "selection_sha256": selection_key,
            "sentence_id": row[0],
            "gender": row[6],
            "reference": row[2],
            "dataset_normalized_reference": row[3],
            "normalized_reference": normalized,
            "normalized_reference_words": len(normalized.split()),
            "audio_sha256": sha256_file(audio_path),
            "audio_bytes": audio_path.stat().st_size,
            "channels": info.channels,
            "sample_rate": info.samplerate,
            "frames": info.frames,
            "duration_seconds": round(info.frames / info.samplerate, 6),
            "resampled": False,
            "channels_converted": False,
            "trimmed_silence": False,
        }

    def totals(self, split: str) -> dict[str, object]:
        rows = [sample for sample in self.samples if sample["split"] == split]
        return {
            "samples": len(rows),
            "duration_seconds": round(sum(float(row["duration_seconds"]) for row in rows), 6),
            "normalized_words": sum(int(row["normalized_reference_words"]) for row in rows),
            "audio_bytes": sum(int(row["audio_bytes"]) for row in rows),
        }

    def check_expectations(self) -> dict[str, object]:
        test = self.totals("test")
        dev = self.totals("dev")
        if test["samples"] != self.expected.test_count:
            raise ValueError(f"Expected {self.expected.test_count} test samples, found {test['samples']}")
        if dev["samples"] != self.expected.dev_count:
            raise ValueError(f"Expected {self.expected.dev_count} dev samples, found {dev['samples']}")
        duration = round(float(test["duration_seconds"]), 2)
        if duration != self.expected.test_duration_seconds:
            raise ValueError(
                "Historical test duration mismatch: "
                f"expected {self.expected.test_duration_seconds:.2f}s, found {duration:.2f}s"
            )
        if int(test["normalized_words"]) != self.expected.test_normalized_words:
            raise ValueError(
                "Historical normalized word count mismatch: "
                f"expected {self.expected.test_normalized_words}, "
                f"found {test['normalized_words']} with {NORMALIZER_PACKAGE}=={NORMALIZER_VERSION}"
            )
        test_files = [str(sample["sample_id"]).split("/", 1)[1] for sample in self.samples if sample["split"] == "test"]
        dev_files = [str(sample["sample_id"]).split("/", 1)[1] for sample in self.samples if sample["split"] == "dev"]
        if self.expected.first_file and test_files[0] != self.expected.first_file:
            raise ValueError(f"Unexpected first test file: {test_files[0]}")
        if self.expected.last_file and test_files[-1] != self.expected.last_file:
            raise ValueError(f"Unexpected last test file: {test_files[-1]}")
        if self.expected.dev_file and dev_files[0] != self.expected.dev_file:
            raise ValueError(f"Unexpected dev file: {dev_files[0]}")
        return {"test": test, "dev": dev}

    def prepare(self) -> dict[str, object]:
        self.reset_data_dir()
        self.events_path.write_text("")
        capacity_before = self.check_capacity()
        self.event("capacity_before", **capacity_before)

        if len(FLEURS_REVISION) != 40:
            raise ValueError("FLEURS_REVISION must be a full commit hash, never a moving default")
        self.normalizer = load_english_normalizer()
        self.event("normalizer_ready", package=NORMALIZER_PACKAGE, version=NORMALIZER_VERSION)

        sources = self.stage_reused_sources() if self.reuse_dir else self.download_sources()
        if self.source_dir.exists():
            shutil.rmtree(self.source_dir)
        for relative in ("data/en_us/test.tsv", "data/en_us/dev.tsv"):
            self.copy_source(relative, sources[relative])

        selected = self.select_sources(sources)
        if self.reuse_dir:
            self.copy_reused_audio(selected)
        else:
            for split, _ in SPLITS:
                self.extract(split, sources[f"data/en_us/audio/{split}.tar.gz"], selected[split])

        self.samples = []
        for split, _ in SPLITS:
            for selection_key, row in selected[split]:
                self.samples.append(self.build_sample(split, selection_key, row))
        identifiers = [sample["sample_id"] for sample in self.samples]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate sample_id in frozen subset")

        totals = self.check_expectations()
        self.event("expectations_verified", **totals)

        selection = {
            "rule": "SHA256(filename) ascending",
            "test_count": self.expected.test_count,
            "dev_count": self.expected.dev_count,
        }
        lock = {
            "schema": LOCK_SCHEMA,
            "repo": FLEURS_REPO,
            "revision": FLEURS_REVISION,
            "endpoint": self.endpoint if not self.reuse_dir else None,
            "source_mode": self.source_mode,
            "reuse_dir": str(self.reuse_dir) if self.reuse_dir else None,
            "selection": selection,
            "normalizer": {"package": NORMALIZER_PACKAGE, "version": NORMALIZER_VERSION},
            "sources": self.sources,
            "source_copies": self.source_copies,
            "created_utc": utc_now(),
        }
        write_json(self.lock_path, lock)

        manifest = {
            "schema": MANIFEST_SCHEMA,
            "repo": FLEURS_REPO,
            "revision": FLEURS_REVISION,
            "endpoint": lock["endpoint"],
            "source_mode": self.source_mode,
            "reuse_dir": lock["reuse_dir"],
            "selection": selection,
            "normalizer": lock["normalizer"],
            "processing": {
                "audio": "original WAV bytes extracted or copied from the pinned revision",
                "resampled": False,
                "channels_converted": False,
                "trimmed_silence": False,
                "target_sample_rate": None,
                "note": (
                    "Leading and trailing silence is retained; PCM16 transport conversion "
                    "belongs to a later replay stage and is accounted separately."
                ),
            },
            "sources": self.sources,
            "source_copies": self.source_copies,
            "totals": totals,
            "samples": self.samples,
        }
        write_json(self.manifest_path, manifest)
        write_json(self.baseline_path, historical_baseline())
        self.event("manifest_written", path=str(self.manifest_path))

        verification = verify_manifest(self.manifest_path, expected=self.expected)

        dataset_bytes = self.directory_bytes(self.data_dir)
        total_asset_bytes = dataset_bytes + self.downloaded_bytes
        if total_asset_bytes > self.asset_limit_bytes:
            raise RuntimeError(
                f"Dataset assets {total_asset_bytes / 1024**3:.2f} GiB exceed the "
                f"{self.asset_limit_bytes / 1024**3:.0f} GiB budget"
            )
        capacity_after = self.disk_stats()
        report = {
            "schema": REPORT_SCHEMA,
            "ok": True,
            "revision": FLEURS_REVISION,
            "source_mode": self.source_mode,
            "reuse_dir": lock["reuse_dir"],
            "endpoint": lock["endpoint"],
            "download_concurrency": DOWNLOAD_CONCURRENCY if not self.reuse_dir else None,
            "totals": totals,
            "verification": verification,
            "capacity": {
                "before": capacity_before,
                "after": capacity_after,
                "dataset_bytes": dataset_bytes,
                "downloaded_source_bytes": self.downloaded_bytes,
                "total_asset_bytes": total_asset_bytes,
                "asset_limit_bytes": self.asset_limit_bytes,
                "minimum_free_bytes_before": self.min_free_bytes,
            },
            "digests": {
                "manifest_sha256": sha256_file(self.manifest_path),
                "lock_sha256": sha256_file(self.lock_path),
                "baseline_sha256": sha256_file(self.baseline_path),
            },
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "note": (
                "No historical manifest was available, so this run records new per-file "
                "hashes and does not claim per-file identity with the deleted old manifest."
            ),
        }
        write_json(self.report_path, report)
        self.event(
            "prepare_complete",
            dataset_bytes=dataset_bytes,
            total_asset_bytes=total_asset_bytes,
            elapsed_seconds=report["elapsed_seconds"],
        )
        return report


def _resolve_audio(dataset_dir: Path, relative: str) -> Path:
    path = (dataset_dir / relative).resolve()
    try:
        path.relative_to(dataset_dir.resolve())
    except ValueError as error:
        raise ValueError(f"Audio path escapes dataset root: {relative}") from error
    return path


def verify_manifest(
    manifest_path: Path,
    expected: Expectations = Expectations(),
    normalizer: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Recompute counts, hashes, selection order and baseline provenance."""
    import soundfile as sf

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_dir = manifest_path.parent
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"Unexpected manifest schema: {manifest.get('schema')!r}")
    if manifest.get("repo") != FLEURS_REPO or manifest.get("revision") != FLEURS_REVISION:
        raise ValueError("Manifest does not point at the pinned FLEURS revision")
    selection = manifest.get("selection", {})
    if selection.get("rule") != "SHA256(filename) ascending":
        raise ValueError("Manifest selection rule changed")
    if normalizer is None:
        normalizer = load_english_normalizer()

    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Manifest has no sample list")
    seen_ids, seen_paths = set(), set()
    totals = {
        split: {"samples": 0, "duration_seconds": 0.0, "normalized_words": 0, "audio_bytes": 0}
        for split, _ in SPLITS
    }
    files_by_split: dict[str, list[str]] = {split: [] for split, _ in SPLITS}
    keys_by_split: dict[str, list[str]] = {split: [] for split, _ in SPLITS}
    for sample in samples:
        split = sample.get("split")
        if split not in totals:
            raise ValueError(f"Unexpected split in manifest: {split!r}")
        sample_id = sample["sample_id"]
        relative = sample["relative_path"]
        if sample_id in seen_ids or relative in seen_paths:
            raise ValueError(f"Duplicate manifest entry: {sample_id}")
        seen_ids.add(sample_id)
        seen_paths.add(relative)
        expected_split = "test" if sample_id.startswith("test/") else "dev" if sample_id.startswith("dev/") else None
        if expected_split != split:
            raise ValueError(f"Sample {sample_id} mixes split identity {split!r}")
        if not relative.startswith(f"audio/{split}/"):
            raise ValueError(f"Sample {sample_id} is stored outside audio/{split}/")
        path = _resolve_audio(dataset_dir, relative)
        if not path.is_file():
            raise ValueError(f"Missing audio file: {relative}")
        if sha256_file(path) != sample["audio_sha256"]:
            raise ValueError(f"Audio digest mismatch: {relative}")
        info = sf.info(str(path))
        if (info.channels, info.samplerate, info.frames) != (
            sample["channels"],
            sample["sample_rate"],
            sample["frames"],
        ):
            raise ValueError(f"Audio metadata mismatch: {relative}")
        duration = info.frames / info.samplerate
        if abs(duration - float(sample["duration_seconds"])) > 1e-6:
            raise ValueError(f"Duration mismatch: {relative}")
        words = count_words(normalizer, sample["reference"])
        if words != sample["normalized_reference_words"]:
            raise ValueError(f"Normalized word count mismatch: {relative}")
        filename = path.name
        key = selection_hash(filename)
        if sample["selection_sha256"] != key:
            raise ValueError(f"Selection key mismatch: {relative}")
        files_by_split[split].append(filename)
        keys_by_split[split].append(key)
        totals[split]["samples"] += 1
        totals[split]["duration_seconds"] += duration
        totals[split]["normalized_words"] += words
        totals[split]["audio_bytes"] += path.stat().st_size

    totals["test"]["duration_seconds"] = round(totals["test"]["duration_seconds"], 6)
    totals["dev"]["duration_seconds"] = round(totals["dev"]["duration_seconds"], 6)
    for split, _ in SPLITS:
        if keys_by_split[split] != sorted(keys_by_split[split]):
            raise ValueError(f"audio/{split} is not ordered by SHA256(filename)")
    if set(files_by_split["test"]) & set(files_by_split["dev"]):
        raise ValueError("test and dev recordings overlap")
    actual_files = {
        split: {str(path.relative_to(dataset_dir)) for path in (dataset_dir / "audio" / split).glob("*.wav")}
        for split, _ in SPLITS
    }
    manifest_files = {
        split: {sample["relative_path"] for sample in samples if sample["split"] == split}
        for split, _ in SPLITS
    }
    for split, _ in SPLITS:
        if actual_files[split] != manifest_files[split]:
            raise ValueError(f"audio/{split} files differ from the manifest; test and dev audio may be mixed")
    for relative, record in manifest.get("source_copies", {}).items():
        path = _resolve_audio(dataset_dir, record["relative_path"])
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ValueError(f"Copied source mismatch: {relative}")
    if totals["test"]["samples"] != expected.test_count:
        raise ValueError(f"Expected {expected.test_count} test samples, found {totals['test']['samples']}")
    if totals["dev"]["samples"] != expected.dev_count:
        raise ValueError(f"Expected {expected.dev_count} dev samples, found {totals['dev']['samples']}")
    if round(totals["test"]["duration_seconds"], 2) != expected.test_duration_seconds:
        raise ValueError(
            f"Test duration {totals['test']['duration_seconds']:.2f}s does not match "
            f"{expected.test_duration_seconds:.2f}s"
        )
    if totals["test"]["normalized_words"] != expected.test_normalized_words:
        raise ValueError(
            f"Test normalized words {totals['test']['normalized_words']} do not match "
            f"{expected.test_normalized_words}"
        )
    if expected.first_file and files_by_split["test"][0] != expected.first_file:
        raise ValueError(f"First test file is {files_by_split['test'][0]}, not {expected.first_file}")
    if expected.last_file and files_by_split["test"][-1] != expected.last_file:
        raise ValueError(f"Last test file is {files_by_split['test'][-1]}, not {expected.last_file}")
    if expected.dev_file and files_by_split["dev"][0] != expected.dev_file:
        raise ValueError(f"Dev file is {files_by_split['dev'][0]}, not {expected.dev_file}")
    if manifest.get("totals") != totals:
        raise ValueError("Stored totals do not match recomputed totals")

    baseline_path = dataset_dir / "historical_asr_baseline.json"
    if not baseline_path.is_file():
        raise ValueError("Historical ASR baseline record is missing")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline != historical_baseline():
        raise ValueError("Historical ASR baseline record differs from the frozen source values")

    return {
        "samples": len(samples),
        "test_samples": totals["test"]["samples"],
        "dev_samples": totals["dev"]["samples"],
        "test_duration_seconds": totals["test"]["duration_seconds"],
        "test_normalized_words": totals["test"]["normalized_words"],
        "first_test_file": files_by_split["test"][0],
        "last_test_file": files_by_split["test"][-1],
        "dev_file": files_by_split["dev"][0],
        "audio_hashes_verified": len(samples),
        "selection_rule_verified": True,
        "historical_baseline_verified": True,
        "historical_baseline_commit": BASELINE_COMMIT,
        "old_manifest_available": False,
        "note": "Hashes were recomputed from this frozen copy, not compared with the deleted old manifest.",
    }


def verify_data(root: Path, expected: Expectations = Expectations()) -> dict[str, object]:
    """Verify a frozen subset and persist a compact verification record."""
    data_dir = root.expanduser().resolve() / "dataset" / "fleurs_en_us"
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    report = verify_manifest(manifest_path, expected=expected)
    record = {
        "schema": VERIFICATION_SCHEMA,
        "verified_utc": utc_now(),
        "manifest_sha256": sha256_file(manifest_path),
        "baseline_sha256": sha256_file(data_dir / "historical_asr_baseline.json"),
        "result": report,
    }
    write_json(data_dir / "verification.json", record)
    return report


class ReplayError(RuntimeError):
    """Fail a replay preflight or sample without hiding the reason."""


def tail_packet_count(tail_silence_seconds: float, packet_ms: int) -> int:
    """Return the number of 80 ms packets that cover the frozen tail window."""
    if tail_silence_seconds <= 0 or packet_ms <= 0:
        raise ValueError("tail duration and packet size must be positive")
    return math.ceil(round(tail_silence_seconds * 1000 / packet_ms, 9))


def load_replay_config(path: Path) -> dict[str, Any]:
    """Load the frozen XTX-002 config and reject replay-incompatible values."""
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema") != REPLAY_CONFIG_SCHEMA:
        raise ReplayError(f"unexpected config schema: {config.get('schema')!r}")
    asr = config["asr"]
    xturnix = config["xturnix"]
    replay = config["replay_contract"]
    triggers = config["triggers"]
    pause = config["pause"]
    if asr["transport"]["packet_ms"] != 80:
        raise ReplayError("transport packet must stay at 80 ms")
    if asr["chunk_ms"] != 160 or asr["lookahead_tokens"] != 1:
        raise ReplayError("ASR must stay on the frozen 160 ms / lookahead=1 setting")
    if asr["dtype"] != "float32" or xturnix["dtype"] != "float32":
        raise ReplayError("both components must stay FP32 in the frozen config")
    if asr["service"]["max_active_sessions"] != 1:
        raise ReplayError("replay requires exactly one active ASR session")
    if xturnix["state"] != "listening":
        raise ReplayError("the replay only measures the Listen contract")
    if tuple(xturnix["allowed_actions"]) != ("<|start|>", "<|keep|>"):
        raise ReplayError("Listen actions must be exactly start/keep")
    scheduler = xturnix["scheduler"]
    if scheduler["max_in_flight"] != 1 or scheduler["max_queued"] != 1:
        raise ReplayError("the control scheduler must allow 1 in-flight and 1 queued")
    if scheduler["queue_policy"] != "latest_prefix_only":
        raise ReplayError("the control queue must retain only the latest prefix")
    if pause["enabled"] or triggers["on_pause_event"]:
        raise ReplayError("pause injection is frozen as disabled for this round")
    if replay["tail_silence_seconds"] != 5 or replay["main_window_seconds"] != 5:
        raise ReplayError("the replay contract requires the 5 s tail and 5 s main window")
    if not replay["shadow_listen"] or replay["stop_asr_on_start"]:
        raise ReplayError("start must remain a shadow decision and must not stop ASR")
    if replay["max_in_flight_control_requests"] != 1:
        raise ReplayError("the replay contract must allow one in-flight control request")
    return config


@dataclass(frozen=True)
class ReplaySettings:
    """Timing and scheduling values used by one replay run."""

    packet_ms: int = 80
    sample_rate_hz: int = 16000
    channels: int = 1
    tail_packets: int = 63
    main_window_seconds: float = 5.0
    poll_interval_seconds: float = 0.05
    asr_timeout_seconds: float = 30.0
    control_timeout_seconds: float = 10.0
    state: str = "listening"
    allowed_actions: tuple[str, ...] = ("<|start|>", "<|keep|>")
    max_in_flight: int = 1
    max_queued: int = 1
    trace_limit_bytes: int = TRACE_LIMIT_BYTES
    min_free_bytes: int = 30 * 1024**3

    @property
    def packet_samples(self) -> int:
        return int(round(self.sample_rate_hz * self.packet_ms / 1000))

    @property
    def packet_bytes(self) -> int:
        return self.packet_samples * self.channels * 2

    @property
    def packet_seconds(self) -> float:
        return self.packet_ms / 1000

    @classmethod
    def from_config(
        cls, config: dict[str, Any], min_free_gib: int = DEFAULT_MIN_FREE_GIB
    ) -> "ReplaySettings":
        asr = config["asr"]
        xturnix = config["xturnix"]
        replay = config["replay_contract"]
        service = asr["service"]
        scheduler = xturnix["scheduler"]
        storage = config["resources"]["storage"]
        packet_ms = int(asr["transport"]["packet_ms"])
        if scheduler["max_in_flight"] != 1 or scheduler["max_queued"] != 1:
            raise ReplayError("ReplaySettings only supports one in-flight and one queued request")
        return cls(
            packet_ms=packet_ms,
            sample_rate_hz=int(asr["transport"]["sample_rate_hz"]),
            channels=int(asr["transport"]["channels"]),
            tail_packets=tail_packet_count(replay["tail_silence_seconds"], packet_ms),
            main_window_seconds=float(replay["main_window_seconds"]),
            poll_interval_seconds=service["poll_interval_ms"] / 1000,
            asr_timeout_seconds=float(service["request_timeout_seconds"]),
            control_timeout_seconds=float(scheduler["request_timeout_seconds"]),
            state=str(xturnix["state"]),
            allowed_actions=tuple(xturnix["allowed_actions"]),
            trace_limit_bytes=int(storage["max_trace_gib"]) * 1024**3,
            min_free_bytes=int(min_free_gib) * 1024**3,
        )


def lexical_tokens(text: str) -> tuple[str, ...]:
    """Return word-like tokens so punctuation-only updates do not look lexical."""
    return tuple(TOKEN_PATTERN.findall(text))


def token_change(
    previous: tuple[str, ...], current: tuple[str, ...]
) -> tuple[list[str], bool]:
    """Return appended tokens and whether the already delivered tail changed."""
    common = 0
    for old, new in zip(previous, current):
        if old != new:
            break
        common += 1
    appended = list(current[common:])
    revised_tail = common < len(previous) and (
        common < len(current) and previous[common] != current[common]
    )
    return appended, revised_tail


class TraceRecorder:
    """Append thread-safe ordered events to one sample trace."""

    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("w", encoding="utf-8")
        self._lock = threading.Lock()
        self._closed = False
        self._sequence = 0
        self.emit("trace_header", **header)

    def emit(self, event: str, at: float | None = None, **fields: Any) -> int:
        with self._lock:
            if self._closed:
                return 0
            self._sequence += 1
            sequence = self._sequence
            record = {
                "seq": sequence,
                "event": event,
                "monotonic": time.monotonic() if at is None else at,
                "utc": utc_now(),
                **fields,
            }
            self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._stream.flush()
            return sequence

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if not self._stream.closed:
                self._stream.close()


class PhaseTracker:
    """Share the current replay phase and marker times across threads."""

    def __init__(self, recorder: TraceRecorder) -> None:
        self.recorder = recorder
        self._lock = threading.Lock()
        self._phase = "pre_audio"
        self.times: dict[str, float] = {}

    def current(self) -> str:
        with self._lock:
            return self._phase

    def set(self, phase: str) -> float:
        now = time.monotonic()
        with self._lock:
            self._phase = phase
            self.times[phase] = now
        self.recorder.emit("replay_phase", at=now, phase=phase)
        return now

    def mark(self, name: str) -> float:
        now = time.monotonic()
        with self._lock:
            self.times[name] = now
        self.recorder.emit("replay_marker", at=now, phase=self.current(), marker=name)
        return now


class AsrClient:
    """Minimal one-session HTTP client for the frozen Nemotron service."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                decoded = json.loads(body or b"{}")
            except json.JSONDecodeError:
                decoded = {"detail": body.decode("utf-8", "replace")[:500]}
            return error.code, decoded

    def health(self) -> dict[str, Any]:
        status, body = self._json("GET", "/health")
        if status != 200:
            raise ReplayError(f"ASR health returned {status}: {body}")
        return body

    def create(self) -> str:
        status, body = self._json("POST", "/v1/session", {})
        if status != 200:
            raise ReplayError(f"ASR create returned {status}: {body}")
        return str(body["session_id"])

    def recognize(
        self,
        session: str,
        pcm: bytes,
        *,
        is_final: bool = False,
        end_stream: bool = False,
    ) -> dict[str, Any]:
        status, body = self._json(
            "POST",
            "/v1/recognize",
            {
                "session_id": session,
                "audio": base64.b64encode(pcm).decode(),
                "is_final": is_final,
                "end_stream": end_stream,
            },
        )
        if status != 200:
            raise ReplayError(f"ASR recognize returned {status}: {body}")
        return body

    def result(self, session: str) -> tuple[int, dict[str, Any]]:
        return self._json("GET", f"/v1/session/{session}/result")

    def close(self, session: str) -> tuple[int, dict[str, Any]]:
        return self._json("DELETE", f"/v1/session/{session}")


def validate_asr_health(health: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    """Reject a service that is not the frozen Nemotron configuration."""
    asr = config["asr"]
    expected_model = str(Path(os.path.expanduser(asr["local_path"])).resolve())
    checks = {
        "health": health.get("status") == "ok",
        "model": str(Path(health.get("model", "")).resolve()) == expected_model,
        "chunk": health.get("chunk_ms") == asr["chunk_ms"],
        "dtype": str(health.get("dtype", "")).removeprefix("torch.") == asr["dtype"],
        "warmup": health.get("warmup_sessions") == 2,
        "offline": health.get("offline") is False,
    }
    if not all(checks.values()):
        raise ReplayError(f"ASR health does not match the frozen config: {health}")
    return checks


class ResultObserver(threading.Thread):
    """Poll ASR prefixes independently of audio sending and control calls."""

    def __init__(
        self,
        client: AsrClient,
        session: str,
        settings: ReplaySettings,
        recorder: TraceRecorder,
        phases: PhaseTracker,
        on_observation: Callable[[dict[str, Any], float, int], None],
    ) -> None:
        super().__init__(daemon=True)
        self.client = client
        self.session = session
        self.settings = settings
        self.recorder = recorder
        self.phases = phases
        self.on_observation = on_observation
        self.stop_event = threading.Event()
        self.error: str | None = None
        self.stuck = False
        self.versions = 0
        self.lexical_changes = 0
        self.last_version = -1
        self.last_text = ""
        self.last_tokens: tuple[str, ...] = ()
        self.final_text = ""

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                status, snapshot = self.client.result(self.session)
            except Exception as error:  # noqa: BLE001 - preserve polling failure
                self.error = f"result observer failed: {error!r}"
                self.recorder.emit("asr_observer_error", error=self.error)
                return
            if status != 200:
                self.error = f"result observer returned {status}: {snapshot}"
                self.recorder.emit("asr_observer_error", status=status, body=snapshot)
                return
            self.observe(snapshot, self.phases.current())
            self.stop_event.wait(self.settings.poll_interval_seconds)

    def observe(
        self,
        snapshot: dict[str, Any],
        phase: str,
        *,
        received: float | None = None,
        notify: bool = True,
    ) -> bool:
        """Record one new prefix version; duplicate versions are ignored."""
        version = int(snapshot.get("prefix_version", -1))
        if version == self.last_version:
            return False
        self.last_version = version
        self.versions += 1
        now = time.monotonic() if received is None else received
        text = str(snapshot.get("text", ""))
        tokens = lexical_tokens(text)
        appended, revised_tail = token_change(self.last_tokens, tokens)
        lexical_change = tokens != self.last_tokens
        if lexical_change:
            self.lexical_changes += 1
        sequence = self.recorder.emit(
            "asr_observation",
            at=now,
            phase=phase,
            session_id=snapshot.get("session_id", self.session),
            prefix_version=version,
            raw_text=snapshot.get("raw_text", text),
            text=text,
            delta=text[len(self.last_text):] if text.startswith(self.last_text) else None,
            token_count=len(tokens),
            appended_tokens=appended,
            revised_tail=revised_tail,
            token_ids_available=False,
            tokenization="unicode_word_pattern",
            lexical_change=lexical_change,
            pause_event=False,
            pause_source=None,
            eof_stage=phase,
            empty=not text.strip(),
        )
        self.last_text, self.last_tokens = text, tokens
        self.final_text = text
        if notify and text.strip():
            self.on_observation(snapshot, now, sequence)
        return True

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=self.settings.asr_timeout_seconds + 1)
        if self.is_alive():
            self.stuck = True
            self.recorder.emit("asr_observer_stuck")


@dataclass(frozen=True)
class ControlObservation:
    request_id: str
    prefix_version: int
    raw_text: str
    observation_seq: int
    observed_monotonic: float
    submitted_monotonic: float


class ControlScheduler(threading.Thread):
    """Run at most one control request and retain only the newest queued prefix."""

    def __init__(
        self,
        controller: Any,
        settings: ReplaySettings,
        recorder: TraceRecorder,
        phases: PhaseTracker,
    ) -> None:
        super().__init__(daemon=True)
        self.controller = controller
        self.settings = settings
        self.recorder = recorder
        self.phases = phases
        self._condition = threading.Condition()
        self._pending: ControlObservation | None = None
        self._closed = False
        self._cutoff: float | None = None
        self._joined = False
        self.stuck = False
        self.started = 0
        self.completed = 0
        self.failed = 0
        self.invalid = 0
        self.superseded = 0
        self.dropped = 0
        self.queued = 0
        self.actions: dict[str, int] = {}
        self.errors: list[str] = []
        self.max_observed_in_flight = 0
        self.late_completions = 0

    def submit(
        self, snapshot: dict[str, Any], observed: float, observation_seq: int
    ) -> None:
        text = str(snapshot.get("text", ""))
        request_id = uuid.uuid4().hex
        observation = ControlObservation(
            request_id=request_id,
            prefix_version=int(snapshot.get("prefix_version", -1)),
            raw_text=text,
            observation_seq=observation_seq,
            observed_monotonic=observed,
            submitted_monotonic=time.monotonic(),
        )
        with self._condition:
            if self._closed:
                self.dropped += 1
                self.recorder.emit(
                    "control_dropped",
                    at=observation.submitted_monotonic,
                    request_id=request_id,
                    input_version=observation.prefix_version,
                    reason="scheduler_closed",
                )
                return
            previous = self._pending
            if previous is not None:
                self.superseded += 1
                self.recorder.emit(
                    "control_superseded",
                    at=observation.submitted_monotonic,
                    request_id=previous.request_id,
                    input_version=previous.prefix_version,
                    replaced_by=request_id,
                    replaced_by_version=observation.prefix_version,
                    reason="latest_prefix_only",
                )
            self._pending = observation
            self.queued += 1
            in_flight = self.started - self.completed - self.failed
            self.recorder.emit(
                "control_queued",
                at=observation.submitted_monotonic,
                request_id=request_id,
                input_version=observation.prefix_version,
                observation_seq=observation_seq,
                observed_monotonic=observed,
                queue_depth=1 if previous is not None else 0,
                in_flight=in_flight,
                phase=self.phases.current(),
            )
            self._condition.notify()

    def run(self) -> None:
        while True:
            with self._condition:
                while not self._closed and self._pending is None:
                    self._condition.wait()
                if self._pending is None:
                    return
                observation = self._pending
                self._pending = None
            try:
                self._execute(observation)
            except Exception as error:  # noqa: BLE001 - keep the scheduler alive
                with self._condition:
                    self.failed += 1
                    self.errors.append(f"{observation.request_id}: {error!r}")
                self.recorder.emit(
                    "control_scheduler_error",
                    request_id=observation.request_id,
                    error=repr(error),
                )

    def _execute(self, observation: ControlObservation) -> None:
        with self._condition:
            self.started += 1
            in_flight = self.started - self.completed - self.failed
            self.max_observed_in_flight = max(self.max_observed_in_flight, in_flight)
            phase = self.phases.current()
        sent = time.monotonic()
        self.recorder.emit(
            "control_request",
            at=sent,
            request_id=observation.request_id,
            input_version=observation.prefix_version,
            observation_seq=observation.observation_seq,
            observed_monotonic=observation.observed_monotonic,
            queue_seconds=sent - observation.submitted_monotonic,
            raw_input=observation.raw_text,
            input_sha256=hashlib.sha256(observation.raw_text.encode()).hexdigest(),
            state=self.settings.state,
            phase=phase,
            shadow=True,
        )
        try:
            result = self.controller.evaluate(observation.raw_text, self.settings.state)
        except Exception as error:  # noqa: BLE001 - a failed call is evidence
            received = time.monotonic()
            with self._condition:
                self.failed += 1
                self.errors.append(f"{observation.request_id}: {error!r}")
            self.recorder.emit(
                "control_failed",
                at=received,
                request_id=observation.request_id,
                input_version=observation.prefix_version,
                error=repr(error),
                inference_seconds=received - sent,
                under_cutoff=self._under_cutoff(received),
                phase=self.phases.current(),
            )
            return

        received = time.monotonic()
        try:
            action = result["action"]
            scores = result["scores"]
            if not isinstance(scores, dict):
                raise TypeError(f"scores must be a dict, found {type(scores).__name__}")
            allowed = tuple(self.settings.allowed_actions)
            numeric = all(isinstance(value, (int, float)) for value in scores.values())
            valid = (
                action in allowed
                and set(scores) == set(allowed)
                and numeric
                and abs(float(sum(scores.values())) - 1.0) < 1e-5
            )
        except Exception as error:  # noqa: BLE001 - malformed output is a contract failure
            with self._condition:
                self.failed += 1
                self.errors.append(f"{observation.request_id}: {error!r}")
            self.recorder.emit(
                "control_failed",
                at=received,
                request_id=observation.request_id,
                input_version=observation.prefix_version,
                error=f"malformed control result: {error!r}",
                inference_seconds=received - sent,
                under_cutoff=self._under_cutoff(received),
                phase=self.phases.current(),
            )
            return
        with self._condition:
            self.completed += 1
            if valid:
                self.actions[action] = self.actions.get(action, 0) + 1
            else:
                self.invalid += 1
                self.errors.append(
                    f"{observation.request_id}: invalid action {action!r} with {scores!r}"
                )
            under_cutoff = self._under_cutoff(received)
            if not under_cutoff:
                self.late_completions += 1
        self.recorder.emit(
            "control_completed",
            at=received,
            request_id=observation.request_id,
            input_version=observation.prefix_version,
            observation_seq=observation.observation_seq,
            raw_input=observation.raw_text,
            normalized_input=result.get("normalized_input"),
            state=result.get("state", self.settings.state),
            action=action,
            scores=scores,
            valid=valid,
            send_monotonic=sent,
            receive_monotonic=received,
            inference_seconds=received - sent,
            under_cutoff=under_cutoff,
            phase="online" if under_cutoff else "post_cutoff",
            shadow=True,
        )

    def _under_cutoff(self, received: float) -> bool:
        with self._condition:
            return self._cutoff is None or received <= self._cutoff

    def close(self, cutoff: float | None = None) -> None:
        with self._condition:
            if not self._closed:
                self._closed = True
                self._cutoff = time.monotonic() if cutoff is None else cutoff
                if self._pending is not None:
                    dropped = self._pending
                    self._pending = None
                    self.dropped += 1
                    self.recorder.emit(
                        "control_dropped",
                        at=self._cutoff,
                        request_id=dropped.request_id,
                        input_version=dropped.prefix_version,
                        reason="online_cutoff",
                    )
                self._condition.notify_all()
        if self._joined:
            return
        self._joined = True
        self.join(timeout=self.settings.control_timeout_seconds + 0.5)
        if self.is_alive():
            self.stuck = True
            self.recorder.emit("control_scheduler_stuck")


class XTurnixController:
    """Load the frozen official pipeline once and run serial shadow decisions."""

    def __init__(self, config: dict[str, Any], model_dir: Path) -> None:
        import torch
        import transformers
        from transformers import pipeline

        if not (model_dir / "turn_pipeline.py").is_file():
            raise ReplayError(f"XTurnix model directory is incomplete: {model_dir}")
        sys.path.insert(0, str(model_dir))
        import turn_pipeline  # noqa: PLC0415 - loaded from the frozen model directory

        self.turn_pipeline = turn_pipeline
        self.model_dir = model_dir
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = config["xturnix"]["dtype"]
        started = time.monotonic()
        self.pipe = pipeline(
            model=str(model_dir),
            trust_remote_code=True,
            device=0 if self.device == "cuda" else -1,
            dtype=self.dtype,
            local_files_only=True,
        )
        self.load_seconds = time.monotonic() - started
        self.max_seq_length = int(self.pipe._configured_max_length())
        expected = int(config["xturnix"]["max_seq_length"])
        if self.max_seq_length != expected:
            raise ReplayError(
                f"XTurnix max_seq_length is {self.max_seq_length}, expected {expected}"
            )
        self.pipeline_version = transformers.__version__
        self._torch = torch

    def normalize(self, text: str) -> str:
        return self.turn_pipeline.strip_trailing_punctuation(text)

    def evaluate(self, text: str, state: str) -> dict[str, Any]:
        normalized = self.normalize(text)
        result = self.pipe([{"role": "user", "content": text}], state=state)
        return {
            "action": result["action"],
            "scores": result["scores"],
            "normalized_input": normalized,
            "state": state,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "model_path": str(self.model_dir),
            "device": self.device,
            "dtype": self.dtype,
            "max_seq_length": self.max_seq_length,
            "transformers": self.pipeline_version,
            "load_seconds": self.load_seconds,
        }

    def close(self) -> None:
        torch = self._torch
        del self.pipe
        if self.device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()


def load_replay_samples(
    manifest_path: Path, split: str = "test", limit: int | None = None
) -> list[dict[str, Any]]:
    """Read the planned sample list from the frozen manifest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ReplayError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise ReplayError("manifest has no sample list")
    if split not in {"test", "dev", "all"}:
        raise ReplayError(f"unsupported split: {split}")
    selected = [dict(sample) for sample in samples if split == "all" or sample["split"] == split]
    if not selected:
        raise ReplayError(f"manifest contains no samples for split {split!r}")
    if limit is not None:
        if limit < 1:
            raise ReplayError("--limit must be positive")
        selected = selected[:limit]
    return selected


def load_replay_audio(
    path: Path, expected_sha256: str, settings: ReplaySettings
) -> tuple[bytes, dict[str, Any]]:
    """Convert frozen WAV bytes to PCM16 without changing the source file."""
    import numpy as np
    import soundfile as sf

    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ReplayError(f"audio digest mismatch: {path}")
    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if rate != settings.sample_rate_hz or audio.shape[1] != settings.channels:
        raise ReplayError(
            f"{path.name} must be {settings.sample_rate_hz} Hz "
            f"{settings.channels}-channel audio"
        )
    if not np.isfinite(audio).all():
        raise ReplayError(f"{path.name} contains non-finite samples")
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    return pcm, {
        "frames": int(audio.shape[0]),
        "duration_seconds": round(audio.shape[0] / rate, 6),
        "pcm_bytes": len(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "resampled": False,
        "channels_converted": False,
        "trimmed_silence": False,
    }


class ReplayRunner:
    """Replay planned samples serially and persist causal traces and statuses."""

    def __init__(
        self,
        output: Path,
        config_path: Path,
        manifest_path: Path,
        samples: list[dict[str, Any]],
        settings: ReplaySettings,
        asr_client: Any,
        controller: Any,
        *,
        split: str = "test",
        limit: int | None = None,
    ) -> None:
        self.output = output.expanduser().resolve()
        self.config_path = config_path.expanduser().resolve()
        self.manifest_path = manifest_path.expanduser().resolve()
        self.samples = samples
        self.settings = settings
        self.asr = asr_client
        self.controller = controller
        self.split = split
        self.limit = limit
        self.started = time.monotonic()
        self.started_utc = utc_now()
        self.status_path = self.output / "status.json"
        self.report_path = self.output / "replay_report.json"
        self.snapshot_path = self.output / "input_snapshot.json"
        self.trace_root = self.output / "traces"
        self.trace_bytes = 0
        self.input_snapshot: dict[str, Any] | None = None

    def prepare(self) -> dict[str, Any]:
        """Create a new run directory and freeze every input actually replayed."""
        if self.output.exists() and any(self.output.iterdir()):
            raise ReplayError(f"Replay output already exists: {self.output}")
        self.output.mkdir(parents=True, exist_ok=True)
        self.trace_root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.output)
        if usage.free < self.settings.min_free_bytes:
            raise ReplayError(
                f"Only {usage.free / 1024**3:.1f} GiB free under {self.output}; "
                f"at least {self.settings.min_free_bytes / 1024**3:.0f} GiB is required"
            )
        stored_config = self.output / "config.json"
        shutil.copyfile(self.config_path, stored_config)
        config_sha = sha256_file(stored_config)
        if config_sha != sha256_file(self.config_path):
            raise ReplayError("stored config differs from the source config")

        import soundfile as sf

        entries = []
        for sample in self.samples:
            audio_path = (self.manifest_path.parent / sample["relative_path"]).resolve()
            try:
                audio_path.relative_to(self.manifest_path.parent.resolve())
            except ValueError as error:
                raise ReplayError(f"audio path escapes dataset root: {sample['relative_path']}") from error
            if not audio_path.is_file():
                raise ReplayError(f"missing audio file: {audio_path}")
            actual = sha256_file(audio_path)
            if actual != sample["audio_sha256"]:
                raise ReplayError(f"input digest mismatch: {sample['sample_id']}")
            info = sf.info(str(audio_path))
            if (info.channels, info.samplerate) != (
                self.settings.channels,
                self.settings.sample_rate_hz,
            ):
                raise ReplayError(f"unexpected audio format: {sample['sample_id']}")
            entries.append(
                {
                    "sample_id": sample["sample_id"],
                    "split": sample["split"],
                    "relative_path": sample["relative_path"],
                    "audio_sha256": actual,
                    "audio_bytes": audio_path.stat().st_size,
                    "frames": info.frames,
                    "sample_rate": info.samplerate,
                    "channels": info.channels,
                    "duration_seconds": round(info.frames / info.samplerate, 6),
                    "reference_included": False,
                }
            )
        self.input_snapshot = {
            "schema": INPUT_SNAPSHOT_SCHEMA,
            "created_utc": self.started_utc,
            "config": {"source_path": str(self.config_path), "sha256": config_sha},
            "manifest": {
                "path": str(self.manifest_path),
                "sha256": sha256_file(self.manifest_path),
            },
            "split": self.split,
            "limit": self.limit,
            "planned_samples": len(entries),
            "packet_ms": self.settings.packet_ms,
            "tail_packets": self.settings.tail_packets,
            "main_window_seconds": self.settings.main_window_seconds,
            "shadow_listen": True,
            "reference_included": False,
            "samples": entries,
        }
        write_json(self.snapshot_path, self.input_snapshot)
        return self.input_snapshot

    def run(self) -> dict[str, Any]:
        if self.input_snapshot is None:
            self.prepare()
        statuses: list[dict[str, Any]] = []
        fatal_reason: str | None = None
        for sample in self.samples:
            if fatal_reason is None:
                status = self._run_one(sample)
                if status.get("fatal_reason"):
                    fatal_reason = status["fatal_reason"]
            else:
                status = self._skipped(sample, fatal_reason)
            statuses.append(status)
            self.trace_bytes += int(status.get("trace_bytes") or 0)
            self._write_status(statuses, fatal_reason)
            if fatal_reason is None and self.trace_bytes > self.settings.trace_limit_bytes:
                fatal_reason = (
                    f"trace limit exceeded: {self.trace_bytes} > "
                    f"{self.settings.trace_limit_bytes} bytes"
                )
        report = self._build_report(statuses, fatal_reason)
        write_json(self.report_path, report)
        return report

    def _skipped(self, sample: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "sample_id": sample["sample_id"],
            "split": sample["split"],
            "status": "skipped",
            "failure_reason": f"not started after fatal sample: {reason}",
            "fatal_reason": None,
            "trace_path": None,
            "trace_bytes": 0,
        }

    def _write_status(
        self, statuses: list[dict[str, Any]], fatal_reason: str | None
    ) -> None:
        counts = {
            "planned": len(self.samples),
            "completed": sum(item["status"] == "completed" for item in statuses),
            "failed": sum(item["status"] == "failed" for item in statuses),
            "skipped": sum(item["status"] == "skipped" for item in statuses),
        }
        write_json(
            self.status_path,
            {
                "schema": REPLAY_STATUS_SCHEMA,
                "updated_utc": utc_now(),
                "counts": counts,
                "fatal_reason": fatal_reason,
                "items": statuses,
            },
        )

    def _run_one(self, sample: dict[str, Any]) -> dict[str, Any]:
        status: dict[str, Any] = {
            "sample_id": sample["sample_id"],
            "split": sample["split"],
            "status": "failed",
            "failure_reason": None,
            "fatal_reason": None,
            "trace_path": None,
            "trace_bytes": 0,
        }
        trace_path = (
            self.trace_root / sample["split"] / f"{Path(sample['relative_path']).stem}.jsonl"
        )
        recorder: TraceRecorder | None = None
        phases: PhaseTracker | None = None
        observer: ResultObserver | None = None
        scheduler: ControlScheduler | None = None
        session: str | None = None
        failure: str | None = None
        fatal: str | None = None
        cutoff: float | None = None
        sample_started = time.monotonic()
        attempted_create = False
        file_packets_sent = 0
        tail_packets_sent = 0
        try:
            recorder = TraceRecorder(
                trace_path,
                {
                    "schema": TRACE_SCHEMA,
                    "sample_id": sample["sample_id"],
                    "split": sample["split"],
                    "relative_path": sample["relative_path"],
                    "audio_sha256": sample["audio_sha256"],
                    "packet_ms": self.settings.packet_ms,
                    "tail_packets": self.settings.tail_packets,
                    "main_window_seconds": self.settings.main_window_seconds,
                    "shadow_listen": True,
                    "stop_asr_on_start": False,
                    "pause_enabled": False,
                    "reference_included": False,
                    "config_sha256": sha256_file(self.output / "config.json"),
                    "manifest_sha256": sha256_file(self.manifest_path),
                },
            )
            phases = PhaseTracker(recorder)
            audio_path = (self.manifest_path.parent / sample["relative_path"]).resolve()
            pcm, audio = load_replay_audio(audio_path, sample["audio_sha256"], self.settings)
            status["pcm_sha256"] = audio["pcm_sha256"]
            status["duration_seconds"] = audio["duration_seconds"]
            recorder.emit(
                "sample_start",
                sample_id=sample["sample_id"],
                split=sample["split"],
                audio=audio,
                planned=True,
                shadow_listen=True,
                reference_included=False,
            )
            packets = [
                pcm[index:index + self.settings.packet_bytes]
                for index in range(0, len(pcm), self.settings.packet_bytes)
            ]
            recorder.emit("replay_plan", file_packets=len(packets),
                          tail_packets=self.settings.tail_packets,
                          packet_ms=self.settings.packet_ms,
                          packet_bytes=self.settings.packet_bytes)

            attempted_create = True
            session = self.asr.create()
            recorder.emit("asr_session_created", session_id=session)

            scheduler = ControlScheduler(self.controller, self.settings, recorder, phases)
            scheduler.start()
            observer = ResultObserver(
                self.asr,
                session,
                self.settings,
                recorder,
                phases,
                on_observation=lambda snapshot, observed, sequence: scheduler.submit(
                    snapshot, observed, sequence
                ),
            )
            observer.start()

            phases.set("file_audio")
            send_started = time.monotonic()
            for index, packet in enumerate(packets):
                deadline = send_started + index * self.settings.packet_seconds
                self._send_packet(
                    session, packet, deadline, recorder, phases, index, "file_audio"
                )
                file_packets_sent += 1
                if observer.error:
                    raise ReplayError(observer.error)
            phases.mark("file_audio_complete")

            phases.set("tail_silence")
            tail_started = time.monotonic()
            for index in range(self.settings.tail_packets):
                deadline = tail_started + index * self.settings.packet_seconds
                self._send_packet(
                    session,
                    SILENCE_PACKET * self.settings.packet_samples,
                    deadline,
                    recorder,
                    phases,
                    index,
                    "tail_silence",
                )
                tail_packets_sent += 1
                if observer.error:
                    raise ReplayError(observer.error)
            tail_end = tail_started + self.settings.tail_packets * self.settings.packet_seconds
            delay = tail_end - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            cutoff = phases.set("post_cutoff")
            recorder.emit("online_cutoff", at=cutoff,
                          phase="post_cutoff",
                          shadow_listen=True)
            scheduler.close(cutoff)
            if scheduler.stuck:
                raise ReplayError("control scheduler did not stop after online cutoff")

            phases.set("eof_drain")
            eof_started = phases.mark("eof_request_started")
            final = self.asr.recognize(session, b"", end_stream=True)
            eof_completed = phases.mark("eof_completed")
            recorder.emit(
                "eof_completed",
                at=eof_completed,
                phase="eof_drain",
                text=final.get("text", ""),
                prefix_version=final.get("prefix_version"),
                ended=final.get("ended"),
                drain_seconds=eof_completed - eof_started,
            )
            observer.stop()
            if observer.stuck:
                fatal = "ASR result observer did not stop"
            status_code, current = self.asr.result(session)
            if status_code != 200:
                raise ReplayError(f"final ASR result returned {status_code}: {current}")
            observer.observe(current, "eof_drain", notify=False)
            recorder.emit(
                "asr_final_snapshot",
                phase="eof_drain",
                text=current.get("text", ""),
                prefix_version=current.get("prefix_version"),
                ended=current.get("ended"),
            )
            if observer.error:
                raise ReplayError(observer.error)
        except Exception as error:  # noqa: BLE001 - the failed sample remains in status
            failure = f"{type(error).__name__}: {error}"
            if attempted_create and session is None:
                fatal = (
                    "ASR session creation failed; single-session service state is "
                    f"unknown: {failure}"
                )
            if recorder is not None:
                recorder.emit("sample_error", phase=phases.current() if phases else None,
                              error=failure)
        finally:
            if observer is not None:
                try:
                    observer.stop()
                except Exception as error:  # noqa: BLE001
                    failure = failure or f"observer stop failed: {error!r}"
                    fatal = fatal or "ASR result observer did not stop"
                if observer.stuck:
                    fatal = fatal or "ASR result observer did not stop"
            if scheduler is not None:
                try:
                    scheduler.close(cutoff)
                except Exception as error:  # noqa: BLE001
                    fatal = fatal or f"control scheduler close failed: {error!r}"
                if scheduler.stuck:
                    fatal = fatal or "control scheduler did not stop"
            if session is not None:
                try:
                    close_status, close_body = self.asr.close(session)
                    if recorder is not None:
                        recorder.emit(
                            "asr_session_closed",
                            status=close_status,
                            body=close_body,
                        )
                    result_status, result_body = self.asr.result(session)
                    if recorder is not None:
                        recorder.emit(
                            "asr_cleanup_verified",
                            status=result_status,
                            body=result_body,
                        )
                    if close_status != 200 or result_status != 404:
                        fatal = fatal or (
                            f"ASR session cleanup failed: close={close_status} "
                            f"result={result_status}"
                        )
                except Exception as error:  # noqa: BLE001 - unisolated session is fatal
                    fatal = fatal or f"ASR session cleanup failed: {error!r}"
            if phases is not None and recorder is not None:
                phases.set("closed")
            if recorder is not None:
                if observer is not None:
                    status["asr_versions"] = observer.versions
                    status["asr_lexical_changes"] = observer.lexical_changes
                    status["final_text"] = observer.final_text
                if scheduler is not None:
                    status.update(
                        {
                            "control_started": scheduler.started,
                            "control_completed": scheduler.completed,
                            "control_failed": scheduler.failed,
                            "control_invalid": scheduler.invalid,
                            "control_superseded": scheduler.superseded,
                            "control_dropped": scheduler.dropped,
                            "control_queued": scheduler.queued,
                            "control_max_in_flight": scheduler.max_observed_in_flight,
                            "control_late_completions": scheduler.late_completions,
                            "actions": dict(scheduler.actions),
                        }
                    )
                    if scheduler.errors:
                        failure = failure or "control error: " + scheduler.errors[0]
                if phases is not None:
                    status["phase_times"] = dict(phases.times)
                status["file_packets_sent"] = file_packets_sent
                status["tail_packets_sent"] = tail_packets_sent
                recorder.emit(
                    "sample_complete",
                    status="failed" if (failure or fatal) else "completed",
                    failure_reason=failure,
                    fatal_reason=fatal,
                )
                recorder.close()
            status["trace_path"] = str(trace_path.relative_to(self.output))
            if trace_path.is_file():
                status["trace_bytes"] = trace_path.stat().st_size
                status["trace_sha256"] = sha256_file(trace_path)

        if observer is not None:
            status.setdefault("asr_versions", observer.versions)
            status.setdefault("asr_lexical_changes", observer.lexical_changes)
            status.setdefault("final_text", observer.final_text)
        if scheduler is not None:
            status.setdefault("control_started", scheduler.started)
            status.setdefault("control_completed", scheduler.completed)
            status.setdefault("control_failed", scheduler.failed)
            status.setdefault("control_invalid", scheduler.invalid)
            status.setdefault("control_superseded", scheduler.superseded)
            status.setdefault("control_dropped", scheduler.dropped)
            status.setdefault("control_queued", scheduler.queued)
            status.setdefault("control_max_in_flight", scheduler.max_observed_in_flight)
            status.setdefault("control_late_completions", scheduler.late_completions)
            status.setdefault("actions", dict(scheduler.actions))
        status.setdefault("file_packets_sent", file_packets_sent)
        status.setdefault("tail_packets_sent", tail_packets_sent)
        status["failure_reason"] = failure
        status["fatal_reason"] = fatal
        status["status"] = "failed" if (failure or fatal) else "completed"
        status["elapsed_seconds"] = round(time.monotonic() - sample_started, 3)
        return status

    def _send_packet(
        self,
        session: str,
        packet: bytes,
        deadline: float,
        recorder: TraceRecorder,
        phases: PhaseTracker,
        index: int,
        kind: str,
    ) -> dict[str, Any]:
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        sent = time.monotonic()
        try:
            response = self.asr.recognize(session, packet)
        except Exception as error:
            recorder.emit(
                "asr_packet_failed",
                at=time.monotonic(),
                packet_index=index,
                kind=kind,
                bytes=len(packet),
                error=repr(error),
                phase=phases.current(),
            )
            raise
        received = time.monotonic()
        recorder.emit(
            "asr_packet_sent",
            at=sent,
            packet_index=index,
            kind=kind,
            bytes=len(packet),
            scheduled_monotonic=deadline,
            lag_seconds=max(0.0, sent - deadline),
            response_seconds=received - sent,
            prefix_version=response.get("prefix_version"),
            phase=phases.current(),
        )
        return response

    def _build_report(
        self, statuses: list[dict[str, Any]], fatal_reason: str | None
    ) -> dict[str, Any]:
        counts = {
            "planned": len(self.samples),
            "completed": sum(item["status"] == "completed" for item in statuses),
            "failed": sum(item["status"] == "failed" for item in statuses),
            "skipped": sum(item["status"] == "skipped" for item in statuses),
            "raw_starts": sum(int(item.get("actions", {}).get("<|start|>", 0)) for item in statuses),
            "keeps": sum(int(item.get("actions", {}).get("<|keep|>", 0)) for item in statuses),
            "control_late_completions": sum(
                int(item.get("control_late_completions") or 0) for item in statuses
            ),
        }
        return {
            "schema": REPLAY_REPORT_SCHEMA,
            "started_utc": self.started_utc,
            "finished_utc": utc_now(),
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "split": self.split,
            "limit": self.limit,
            "counts": counts,
            "fatal_reason": fatal_reason,
            "config": {
                "source_path": str(self.config_path),
                "sha256": sha256_file(self.output / "config.json")
                if (self.output / "config.json").is_file()
                else None,
            },
            "manifest": {
                "path": str(self.manifest_path),
                "sha256": sha256_file(self.manifest_path),
            },
            "input_snapshot": {
                "path": str(self.snapshot_path.relative_to(self.output)),
                "sha256": sha256_file(self.snapshot_path),
            },
            "controller": self.controller.describe()
            if hasattr(self.controller, "describe")
            else None,
            "traces": {
                "root": "traces",
                "bytes": self.trace_bytes,
                "limit_bytes": self.settings.trace_limit_bytes,
                "within_limit": self.trace_bytes <= self.settings.trace_limit_bytes,
            },
            "status_path": str(self.status_path.relative_to(self.output)),
            "note": (
                "This report only records replay execution and causal events. "
                "It computes no start latency, WER or model-quality metric; XTX-004 "
                "scores the traces offline. Simulated services in tests do not "
                "represent real Nemotron or XTurnix results."
            ),
        }


def run_replay(
    root: Path,
    config_path: Path,
    output: Path | None,
    run_id: str | None,
    split: str,
    limit: int | None,
    model_dir: Path | None,
    asr_url: str | None,
    min_free_gib: int,
) -> dict[str, Any]:
    """Load the frozen services and replay the selected manifest samples."""
    config = load_replay_config(config_path)
    settings = ReplaySettings.from_config(config, min_free_gib=min_free_gib)
    data_dir = root.expanduser().resolve() / "dataset" / "fleurs_en_us"
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ReplayError(f"Manifest not found: {manifest_path}")
    samples = load_replay_samples(manifest_path, split=split, limit=limit)
    run_id = run_id or "xtx-003-replay-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (
        output.expanduser().resolve()
        if output
        else (root.expanduser().resolve() / "runs" / run_id / "replay")
    )
    model_dir = (
        model_dir.expanduser().resolve()
        if model_dir
        else Path(os.path.expanduser(config["xturnix"]["local_path"])).resolve()
    )
    base_url = asr_url or config["asr"]["service"]["base_url"]
    asr = AsrClient(base_url, settings.asr_timeout_seconds)
    health = asr.health()
    validate_asr_health(health, config)
    controller = XTurnixController(config, model_dir)
    try:
        runner = ReplayRunner(
            output,
            config_path,
            manifest_path,
            samples,
            settings,
            asr,
            controller,
            split=split,
            limit=limit,
        )
        report = runner.run()
        report["asr_health"] = health
        report["asr_base_url"] = base_url
        write_json(runner.report_path, report)
        return report
    finally:
        controller.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-data", help="freeze the pinned FLEURS subset")
    prepare.add_argument("--root", type=Path, required=True, help="remote workspace root")
    prepare.add_argument(
        "--endpoint",
        default=os.environ.get("HF_ENDPOINT", DEFAULT_HF_ENDPOINT),
        help="Hugging Face endpoint; the resolved endpoint is recorded in the lock",
    )
    prepare.add_argument(
        "--reuse-dir",
        type=Path,
        help="read-only FLEURS dataset directory or workspace root from an earlier verified run",
    )
    prepare.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing dataset/fleurs_en_us freeze",
    )
    prepare.add_argument("--min-free-gib", type=int, default=DEFAULT_MIN_FREE_GIB)
    prepare.add_argument("--asset-limit-gib", type=int, default=DEFAULT_ASSET_LIMIT_GIB)

    verify = sub.add_parser("verify-data", help="recheck an existing frozen subset")
    verify.add_argument("--root", type=Path, required=True, help="remote workspace root")

    replay = sub.add_parser("replay", help="replay frozen audio and record causal traces")
    replay.add_argument("--root", type=Path, required=True, help="remote workspace root")
    replay.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parents[2] / "configs" / "xturnix_fleurs_test.json",
        help="frozen XTX-002 component config",
    )
    replay.add_argument("--output", type=Path, help="new replay output directory")
    replay.add_argument("--run-id", help="run identifier used under <root>/runs/")
    replay.add_argument("--split", choices=("test", "dev", "all"), default="test")
    replay.add_argument("--limit", type=int, help="replay only the first N planned samples")
    replay.add_argument("--model", type=Path, help="frozen XTurnix model directory")
    replay.add_argument("--asr-url", help="override the frozen ASR service URL")
    replay.add_argument("--min-free-gib", type=int, default=DEFAULT_MIN_FREE_GIB)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-data":
            preparer = DatasetPreparer(
                args.root,
                endpoint=args.endpoint,
                reuse_dir=args.reuse_dir,
                overwrite=args.overwrite,
                min_free_gib=args.min_free_gib,
                asset_limit_gib=args.asset_limit_gib,
            )
            print(json.dumps(preparer.prepare(), ensure_ascii=False, indent=2))
            return
        if args.command == "replay":
            report = run_replay(
                args.root,
                args.config,
                args.output,
                args.run_id,
                args.split,
                args.limit,
                args.model,
                args.asr_url,
                args.min_free_gib,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        print(json.dumps(verify_data(args.root), ensure_ascii=False, indent=2))
    except ReplayError as error:
        print(f"replay error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
