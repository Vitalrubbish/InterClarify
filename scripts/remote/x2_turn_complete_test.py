"""Restore and verify the pinned FLEURS English subset for the X2-Turn test.

This module currently owns the data stage only.  Replay and scoring stages are
added by later work items; keeping the entry point here avoids reviving the old
ASR-selection script with its unpinned revision fallback.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
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
NORMALIZER_PACKAGE = "whisper-normalizer"
NORMALIZER_VERSION = "0.1.12"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"
DEFAULT_MIN_FREE_GIB = 100
DEFAULT_ASSET_LIMIT_GIB = 70
DOWNLOAD_CONCURRENCY = 1

SPLITS = (("test", TEST_COUNT), ("dev", DEV_COUNT))


@dataclass(frozen=True)
class Expectations:
    """Frozen totals that a restored subset must reproduce."""

    test_count: int = TEST_COUNT
    dev_count: int = DEV_COUNT
    test_duration_seconds: float = EXPECTED_TEST_DURATION_SECONDS
    test_normalized_words: int = EXPECTED_TEST_NORMALIZED_WORDS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def selection_hash(filename: str) -> str:
    """Reproduce the historical SHA256(filename) selection key."""
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
        if Path(filename).name != filename or not filename:
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
    """Load exactly whisper-normalizer 0.1.12 used by the historical report."""
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

    normalizer = EnglishTextNormalizer()
    return normalizer


def count_words(normalizer: Callable[[str], str], text: str) -> int:
    return len(normalizer(text).split())


class DatasetPreparer:
    """Download, select, extract and freeze the 100 test + 1 dev recordings."""

    def __init__(
        self,
        root: Path,
        endpoint: str = DEFAULT_HF_ENDPOINT,
        expected: Expectations = Expectations(),
        min_free_gib: int = DEFAULT_MIN_FREE_GIB,
        asset_limit_gib: int = DEFAULT_ASSET_LIMIT_GIB,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.endpoint = endpoint.rstrip("/")
        self.expected = expected
        self.min_free_bytes = min_free_gib * 1024**3
        self.asset_limit_bytes = asset_limit_gib * 1024**3
        self.data_dir = self.root / "dataset" / "fleurs_en_us"
        self.source_dir = self.data_dir / "source" / "en_us"
        self.events_path = self.data_dir / "prepare_events.jsonl"
        self.lock_path = self.data_dir / "dataset.lock.json"
        self.manifest_path = self.data_dir / "manifest.json"
        self.report_path = self.data_dir / "prepare_report.json"
        self.normalizer: Callable[[str], str] | None = None
        self.started = time.monotonic()
        self.sources: dict[str, dict[str, object]] = {}
        self.source_copies: dict[str, dict[str, object]] = {}
        self.samples: list[dict[str, object]] = []

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
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": digest,
            "revision": FLEURS_REVISION,
        }
        self.event(
            "download_complete",
            file=relative,
            bytes=path.stat().st_size,
            sha256=digest,
            seconds=round(time.monotonic() - started, 3),
        )
        return path

    def copy_source(self, relative: str, path: Path) -> None:
        """Keep the small TSV files beside the manifest for offline auditing."""
        destination = self.source_dir / relative
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
        return {"test": test, "dev": dev}

    def prepare(self) -> dict[str, object]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text("")
        capacity_before = self.check_capacity()
        self.event("capacity_before", **capacity_before)

        if len(FLEURS_REVISION) != 40:
            raise ValueError("FLEURS_REVISION must be a full commit hash, never a moving default")
        self.normalizer = load_english_normalizer()
        self.event("normalizer_ready", package=NORMALIZER_PACKAGE, version=NORMALIZER_VERSION)

        sources = {}
        for relative in (
            "data/en_us/test.tsv",
            "data/en_us/dev.tsv",
            "data/en_us/audio/test.tar.gz",
            "data/en_us/audio/dev.tar.gz",
        ):
            sources[relative] = self.fetch_source(relative)
        for relative in ("data/en_us/test.tsv", "data/en_us/dev.tsv"):
            self.copy_source(relative, sources[relative])

        selected = {}
        for split, limit in SPLITS:
            rows = read_tsv(sources[f"data/en_us/{split}.tsv"])
            selected[split] = select_rows(rows, limit)
            self.event(
                "selection_complete",
                split=split,
                available=len(rows),
                selected=len(selected[split]),
                rule="sha256(filename) ascending",
                first_file=selected[split][0][1],
                last_file=selected[split][-1][1],
            )
        test_names = {row[1] for _, row in selected["test"]}
        dev_names = {row[1] for _, row in selected["dev"]}
        if test_names & dev_names:
            raise ValueError("A recording was selected for both test and dev")

        for split, _ in SPLITS:
            self.extract(split, sources[f"data/en_us/audio/{split}.tar.gz"], selected[split])

        self.samples = []
        for split, _ in SPLITS:
            for selection_key, row in selected[split]:
                self.samples.append(self.build_sample(split, selection_key, row))
        identifiers = [sample["sample_id"] for sample in self.samples]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate sample_id in restored subset")

        totals = self.check_expectations()
        self.event("expectations_verified", **totals)

        lock = {
            "schema": "x2q-009-fleurs-lock-v1",
            "repo": FLEURS_REPO,
            "revision": FLEURS_REVISION,
            "endpoint": self.endpoint,
            "selection": {
                "rule": "SHA256(filename) ascending",
                "test_count": self.expected.test_count,
                "dev_count": self.expected.dev_count,
            },
            "normalizer": {"package": NORMALIZER_PACKAGE, "version": NORMALIZER_VERSION},
            "sources": self.sources,
            "source_copies": self.source_copies,
            "created_utc": utc_now(),
        }
        write_json(self.lock_path, lock)

        manifest = {
            "schema": "x2q-009-fleurs-manifest-v1",
            "repo": FLEURS_REPO,
            "revision": FLEURS_REVISION,
            "endpoint": self.endpoint,
            "selection": lock["selection"],
            "normalizer": lock["normalizer"],
            "processing": {
                "audio": "original WAV bytes extracted from the pinned archives",
                "resampled": False,
                "channels_converted": False,
                "trimmed_silence": False,
                "target_sample_rate": None,
                "note": "Leading and trailing silence is retained; no human speech-end labels were added.",
            },
            "sources": self.sources,
            "source_copies": self.source_copies,
            "totals": totals,
            "samples": self.samples,
        }
        write_json(self.manifest_path, manifest)
        self.event("manifest_written", path=str(self.manifest_path))
        verification = verify_manifest(self.manifest_path, expected=self.expected)

        dataset_bytes = self.directory_bytes(self.data_dir)
        if dataset_bytes > self.asset_limit_bytes:
            raise RuntimeError(
                f"Dataset asset size {dataset_bytes / 1024**3:.2f} GiB exceeds the "
                f"{self.asset_limit_bytes / 1024**3:.0f} GiB budget"
            )
        capacity_after = self.disk_stats()
        report = {
            "schema": "x2q-009-prepare-report-v1",
            "ok": True,
            "revision": FLEURS_REVISION,
            "endpoint": self.endpoint,
            "download_concurrency": DOWNLOAD_CONCURRENCY,
            "totals": totals,
            "verification": verification,
            "capacity": {
                "before": capacity_before,
                "after": capacity_after,
                "dataset_bytes": dataset_bytes,
                "asset_limit_bytes": self.asset_limit_bytes,
                "minimum_free_bytes_before": self.min_free_bytes,
            },
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "note": (
                "No historical manifest was available, so this run records new per-file "
                "hashes and does not claim per-file identity with the deleted old manifest."
            ),
        }
        write_json(self.report_path, report)
        self.event("prepare_complete", dataset_bytes=dataset_bytes, elapsed_seconds=report["elapsed_seconds"])
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
    """Recompute counts, hashes and audio metadata from the frozen manifest."""
    import soundfile as sf

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_dir = manifest_path.parent
    if manifest.get("repo") != FLEURS_REPO or manifest.get("revision") != FLEURS_REVISION:
        raise ValueError("Manifest does not point at the pinned FLEURS revision")
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
        totals[split]["samples"] += 1
        totals[split]["duration_seconds"] += duration
        totals[split]["normalized_words"] += words
        totals[split]["audio_bytes"] += path.stat().st_size

    totals["test"]["duration_seconds"] = round(totals["test"]["duration_seconds"], 6)
    totals["dev"]["duration_seconds"] = round(totals["dev"]["duration_seconds"], 6)
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
    if manifest.get("totals") != totals:
        raise ValueError("Stored totals do not match recomputed totals")
    return {
        "samples": len(samples),
        "test_samples": totals["test"]["samples"],
        "dev_samples": totals["dev"]["samples"],
        "test_duration_seconds": totals["test"]["duration_seconds"],
        "test_normalized_words": totals["test"]["normalized_words"],
        "audio_hashes_verified": len(samples),
        "old_manifest_available": False,
        "note": "Hashes were recomputed from this restored copy, not compared with the deleted old manifest.",
    }


def summarize(report: dict[str, object]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-data", help="download and freeze the pinned FLEURS subset")
    prepare.add_argument("--root", type=Path, required=True, help="remote workspace root")
    prepare.add_argument(
        "--endpoint",
        default=os.environ.get("HF_ENDPOINT", DEFAULT_HF_ENDPOINT),
        help="Hugging Face endpoint; the resolved endpoint is recorded in the lock",
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
            min_free_gib=args.min_free_gib,
            asset_limit_gib=args.asset_limit_gib,
        )
        summarize(preparer.prepare())
        return
    manifest_path = args.root.expanduser().resolve() / "dataset" / "fleurs_en_us" / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    summarize(verify_manifest(manifest_path))


if __name__ == "__main__":
    main()
