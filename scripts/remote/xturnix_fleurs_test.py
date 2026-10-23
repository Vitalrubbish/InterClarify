"""Freeze the FLEURS subset and historical ASR baseline for the XTurnix test."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

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

    args = parser.parse_args(argv)
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
    print(json.dumps(verify_data(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
