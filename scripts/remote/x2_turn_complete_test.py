"""Restore frozen FLEURS data, replay real-time sessions and score raw traces."""

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
        if self.source_dir.exists():
            shutil.rmtree(self.source_dir)
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
        downloaded_source_bytes = sum(int(record["bytes"]) for record in self.sources.values())
        total_asset_bytes = dataset_bytes + downloaded_source_bytes
        if total_asset_bytes > self.asset_limit_bytes:
            raise RuntimeError(
                f"Dataset assets {total_asset_bytes / 1024**3:.2f} GiB exceed the "
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
                "downloaded_source_bytes": downloaded_source_bytes,
                "total_asset_bytes": total_asset_bytes,
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


TURN_CLASSES = {35: "idle", 36: "noidle", 37: "speaking", 38: "turn_end",
                39: "backchannel", 40: "uncertain"}
SAMPLE_RATE = 16000
CHUNK_FRAMES = 1280
WINDOW_SECONDS = 5.0
DRAIN_SECONDS = 60.0


class StreamingReplay:
    """Own one paced input session and its independent receive journal."""

    def __init__(self, url: str, model: str, journal=None):
        self.url, self.model, self.journal = url, model, journal
        self.trace = {"schema": "x2q-stream-v1", "events": [], "sends": [],
                      "t_start": None, "t_end": None, "window_end": None,
                      "window_observed": False, "t_eof": None,
                      "t_eof_sent": None, "t_done": None,
                      "online_text": "", "final_text": "", "errors": [],
                      "status": "failed", "exit_code": 1}
        self.text = ""

    def record(self, kind: str, **fields) -> dict:
        row = {"kind": kind, "monotonic": time.monotonic(), "utc": utc_now(), **fields}
        if self.journal:
            self.journal(row)
        return row

    async def receive(self, socket):
        async for message in socket:
            # Timestamp before JSON parsing or any file I/O.
            received = time.monotonic()
            try:
                payload = json.loads(message)
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
            except (ValueError, TypeError) as error:
                self.trace["events"].append(self.record(
                    "receive", received=received, raw=message, parse_error=str(error)))
                raise ValueError("Invalid server JSON") from error
            kind = payload.get("type")
            if kind == "transcription.delta":
                self.text += payload.get("delta", "")
            elif kind == "transcription.done":
                self.text = payload["text"]
                self.trace["t_done"] = received
            row = self.record("receive", received=received, payload=payload,
                              cumulative_text=self.text)
            self.trace["events"].append(row)
            if kind == "error":
                raise RuntimeError(f"Server error: {payload}")
            if kind == "transcription.done":
                if self.trace["t_eof"] is None:
                    raise RuntimeError("transcription.done before EOF")
                return
        raise ConnectionError("Disconnected before transcription.done")

    async def send_audio(self, socket, pcm: bytes):
        import asyncio
        import base64

        await socket.send(json.dumps({"type": "session.update", "model": self.model}))
        start = time.monotonic()
        self.trace["t_start"] = start
        self.trace["planned_file_end"] = start + len(pcm) / 2 / SAMPLE_RATE

        async def send_chunk(chunk, phase, deadline):
            await asyncio.sleep(max(0, deadline - time.monotonic()))
            began = time.monotonic()
            await socket.send(json.dumps({"type": "input_audio_buffer.append",
                                          "audio": base64.b64encode(chunk).decode("ascii")}))
            await socket.send(json.dumps({"type": "input_audio_buffer.commit", "final": False}))
            self.trace["sends"].append(self.record(
                "send", phase=phase, deadline=deadline, began=began,
                frames=len(chunk) // 2, lateness_ms=max(0, began - deadline) * 1000))

        for offset in range(0, len(pcm), CHUNK_FRAMES * 2):
            chunk = pcm[offset:offset + CHUNK_FRAMES * 2]
            await send_chunk(chunk, "input", start + (offset + len(chunk)) / 2 / SAMPLE_RATE)
        end = time.monotonic()
        self.trace.update(t_end=end, window_end=end + WINDOW_SECONDS)
        self.record("input_end", t_end=end, window_end=end + WINDOW_SECONDS)
        frames = int(WINDOW_SECONDS * SAMPLE_RATE)
        for offset in range(0, frames, CHUNK_FRAMES):
            count = min(CHUNK_FRAMES, frames - offset)
            await send_chunk(b"\0\0" * count, "silence", end + (offset + count) / SAMPLE_RATE)
        self.trace["window_observed"] = True
        self.trace["online_text"] = next(
            (event["cumulative_text"] for event in reversed(self.trace["events"])
             if event["received"] <= self.trace["window_end"]), "")
        self.trace["t_eof"] = time.monotonic()
        self.record("eof_requested", online_text=self.text)
        await socket.send(json.dumps({"type": "input_audio_buffer.commit", "final": True}))
        self.trace["t_eof_sent"] = time.monotonic()
        self.record("eof_sent")

    async def run(self, pcm: bytes) -> dict:
        import asyncio
        import websockets

        tasks = []
        try:
            async with websockets.connect(self.url, max_size=2 * 1024**2,
                                          open_timeout=20, close_timeout=5) as socket:
                receiver = asyncio.create_task(self.receive(socket))
                sender = asyncio.create_task(self.send_audio(socket, pcm))
                tasks = [receiver, sender]
                finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if receiver in finished:
                    await receiver
                    if not sender.done():
                        raise RuntimeError("Receiver stopped before EOF completed")
                await sender
                await asyncio.wait_for(receiver, timeout=DRAIN_SECONDS)
                self.trace.update(status="ok", exit_code=0)
        except Exception as error:
            self.trace["errors"].append({"type": type(error).__name__, "message": str(error)})
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.trace["final_text"] = self.text
            self.trace["t_exit"] = time.monotonic()
        return self.trace


def read_replay_audio(path: Path) -> bytes:
    import numpy as np
    import soundfile as sf

    info = sf.info(str(path))
    if (info.channels, info.samplerate) != (1, SAMPLE_RATE):
        raise ValueError("Replay requires mono 16000 Hz WAV without resampling or channel changes")
    data, _ = sf.read(str(path), dtype="float32", always_2d=True)
    if not data.size:
        raise ValueError("Empty input audio")
    # FLEURS keeps some inputs as 32-bit float.  Scale to the PCM16 the
    # realtime API expects without resampling or trimming the frozen samples.
    scaled = np.rint(data[:, 0].astype(np.float32) * 32768.0)
    pcm = np.clip(scaled, -32768, 32767).astype("<i2")
    return pcm.tobytes()


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)

    def percentile(q):
        position = (len(ordered) - 1) * q
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {"count": len(ordered), "mean_ms": sum(ordered) / len(ordered) if ordered else None,
            "p50_ms": percentile(.5) if ordered else None,
            "p95_ms": percentile(.95) if ordered else None,
            "max_ms": max(ordered) if ordered else None}


def score_complete(trace: dict) -> dict:
    end, window, eof = (trace.get(key) for key in ("t_end", "window_end", "t_eof"))
    before, inside, after_eof, outside, anomalies = [], [], [], [], []
    for event in trace.get("events", []):
        payload = event.get("payload", {})
        if payload.get("type") != "turn.delta":
            continue
        identifier = payload.get("turn_id")
        if type(identifier) is not int or TURN_CLASSES.get(identifier) != payload.get("turn_class"):
            anomalies.append(event)
            continue
        if identifier != 38:
            continue
        received = event["received"]
        if eof is not None and received >= eof:
            after_eof.append(received)
        elif end is not None and received < end:
            before.append(received)
        elif end is not None and window is not None and end <= received <= window:
            inside.append(received)
        else:
            outside.append(received)
    ok = trace.get("status") == "ok" and trace.get("window_observed", False) and not anomalies
    return {"hit": bool(inside), "latency_ms": (min(inside) - end) * 1000 if inside else None,
            "replay_ok": ok, "window_observed": trace.get("window_observed", False),
            "before_count": len(before), "window_count": len(inside),
            "after_eof_count": len(after_eof), "outside_count": len(outside),
            "only_before": bool(before) and not (inside or after_eof or outside),
            "only_after_eof": bool(after_eof) and not (before or inside or outside),
            "never_observed": not (before or inside or after_eof or outside),
            "protocol_anomalies": anomalies,
            "complete_absent_full_window": not inside if trace.get("window_observed") else None}


def word_errors(reference: list[str], hypothesis: list[str]) -> dict:
    """Levenshtein counts with deterministic substitution/deletion/insertion ties."""
    previous = [(j, 0, 0, j) for j in range(len(hypothesis) + 1)]
    for i, ref in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, hyp in enumerate(hypothesis, 1):
            if ref == hyp:
                current.append(previous[j - 1])
                continue
            cost, s, d, ins = previous[j - 1]
            sub = (cost + 1, s + 1, d, ins)
            cost, s, d, ins = previous[j]
            delete = (cost + 1, s, d + 1, ins)
            cost, s, d, ins = current[j - 1]
            insert = (cost + 1, s, d, ins + 1)
            current.append(min((sub, delete, insert), key=lambda row: row[0]))
        previous = current
    cost, s, d, ins = previous[-1]
    return {"S": s, "D": d, "I": ins, "N_ref": len(reference),
            "wer": cost / len(reference) if reference else None}


def lexical_text(text: str) -> str:
    import unicodedata

    # Punctuation updates must not change the last lexical reception time.
    return " ".join("".join(c for c in text.casefold()
                            if not unicodedata.category(c).startswith("P")).split())


def score_asr(trace: dict, reference: str, normalizer: Callable[[str], str]) -> dict:
    ref = normalizer(reference)
    final = trace.get("final_text", "")
    hyp = normalizer(final)
    ok = trace.get("status") == "ok"
    last_online = None
    online_text = ""
    previous = ""
    post_changes = []
    end, window, eof = (trace.get(key) for key in ("t_end", "window_end", "t_eof"))
    for event in trace.get("events", []):
        if event.get("payload", {}).get("type") not in ("transcription.delta", "transcription.done"):
            continue
        text = event["cumulative_text"]
        lexical = lexical_text(text)
        received = event["received"]
        changed = lexical != previous
        previous = lexical
        if window is not None and received <= window and (eof is None or received < eof):
            online_text = text
            if changed:
                last_online = received
        if changed and eof is not None and received >= eof:
            post_changes.append({"received": received, "after_eof_ms": (received - eof) * 1000,
                                 "after_end_ms": (received - end) * 1000 if end is not None else None,
                                 "text": text})
    latency = ((last_online - end) * 1000
               if ok and hyp and end is not None and last_online is not None and lexical_text(online_text) else None)
    errors = word_errors(ref.split(), hyp.split()) if ok else None
    return {"scorable": ok, "reference": reference, "normalized_reference": ref,
            "N_ref": len(ref.split()), "wer": errors["wer"] if errors else None,
            "final_hypothesis": final, "normalized_hypothesis": hyp,
            "errors": errors,
            "online_text": online_text, "text_latency_ms": latency,
            "eof_lexical_updates": post_changes,
            "eof_last_update_ms": post_changes[-1]["after_eof_ms"] if post_changes else None,
            "eof_text_changed": lexical_text(final) != lexical_text(online_text)}


async def replay_run(args) -> dict:
    manifest_path = args.root.expanduser().resolve() / "dataset/fleurs_en_us/manifest.json"
    verify_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    split, limit = {"formal": ("test", 100), "smoke": ("test", 5), "dev": ("dev", 1)}[args.mode]
    samples = [s for s in manifest["samples"] if s["split"] == split][:limit]
    if len(samples) != limit:
        raise ValueError("Frozen manifest does not contain the planned samples")
    if not args.run_id or Path(args.run_id).name != args.run_id or args.run_id in (".", ".."):
        raise ValueError("run_id must be a single directory name")
    output = manifest_path.parents[2] / "runs" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(manifest_path, output / "manifest.json")
    plan = {"schema": "x2q-run-v1", "mode": args.mode, "run_id": args.run_id,
            "created_utc": utc_now(), "manifest_sha256": sha256_file(manifest_path),
            "url": args.url, "model": args.model, "chunk_ms": 80,
            "window_seconds": WINDOW_SECONDS, "drain_seconds": DRAIN_SECONDS,
            "samples": [{"sample_id": s["sample_id"], "trace": f"{i:03d}.json"}
                        for i, s in enumerate(samples)]}
    write_json(output / "run.json", plan)
    # Allocate a failure record for every planned input before opening any session.
    for item in plan["samples"]:
        write_json(output / item["trace"], {"schema": "x2q-stream-v1", "status": "failed",
                   "sample_id": item["sample_id"], "exit_code": 1,
                   "errors": [{"type": "NotStarted", "message": "Replay did not finish"}]})
    used_bytes = sum(p.stat().st_size for p in output.iterdir() if p.is_file())
    for item, sample in zip(plan["samples"], samples):
        with (output / (item["trace"] + "l")).open("x", encoding="utf-8") as journal:
            def append(row):
                nonlocal used_bytes
                encoded = json.dumps(row, ensure_ascii=False) + "\n"
                used_bytes += len(encoded.encode("utf-8"))
                # Reserve space for the finalized trace copies, across the whole run.
                if used_bytes * 3 > 5 * 1024**3:
                    raise RuntimeError("Run result budget exceeded (5 GiB)")
                journal.write(encoded)
                journal.flush()

            replay = StreamingReplay(args.url, args.model, append)
            try:
                path = _resolve_audio(manifest_path.parent, sample["relative_path"])
                pcm = read_replay_audio(path)
                import asyncio
                trace = await asyncio.wait_for(replay.run(pcm), len(pcm) / 2 / SAMPLE_RATE + 120)
            except Exception as error:
                trace = replay.trace
                trace["errors"].append({"type": type(error).__name__, "message": str(error)})
            trace["sample_id"] = item["sample_id"]
            write_json(output / item["trace"], trace)
    return {"run": str(output), "planned": len(samples)}


def score_run(run: Path, metric: str) -> dict:
    plan = json.loads((run / "run.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if sha256_file(run / "manifest.json") != plan["manifest_sha256"]:
        raise ValueError("Run manifest no longer matches the frozen input")
    references = {s["sample_id"]: s for s in manifest["samples"]}
    normalizer = load_english_normalizer() if metric == "asr" else None
    if metric == "asr":
        if manifest.get("normalizer") != {"package": NORMALIZER_PACKAGE, "version": NORMALIZER_VERSION}:
            raise ValueError("Manifest normalizer version mismatch")
        total = sum(len(normalizer(s["reference"]).split()) for s in manifest["samples"] if s["split"] == "test")
        if total != EXPECTED_TEST_NORMALIZED_WORDS:
            raise ValueError("Frozen test reference word count does not equal 2162")
    rows = []
    for item in plan["samples"]:
        path = run / item["trace"]
        trace = json.loads(path.read_text()) if path.exists() else {"status": "failed", "errors": [{"type": "MissingTrace"}]}
        if trace.get("sample_id", item["sample_id"]) != item["sample_id"]:
            raise ValueError("Trace sample identity mismatch")
        score = (score_asr(trace, references[item["sample_id"]]["reference"], normalizer)
                 if metric == "asr" else score_complete(trace))
        rows.append({"sample_id": item["sample_id"], **score,
                     "runtime_errors": trace.get("errors", []), "exit_code": trace.get("exit_code", 1)})
    planned = len(rows)
    summary = {"mode": plan["mode"], "planned": planned,
               "formal_samples": planned if plan["mode"] == "formal" else 0}
    if metric == "asr":
        valid = [r for r in rows if r["scorable"]]
        counts = {key: sum(r["errors"][key] for r in valid) for key in ("S", "D", "I", "N_ref")}
        summary.update(scorable=len(valid), failed=planned - len(valid),
                       planned_reference_words=sum(r["N_ref"] for r in rows),
                       scorable_coverage=len(valid) / planned if planned else None,
                       normalizer={"package": NORMALIZER_PACKAGE, "version": NORMALIZER_VERSION},
                       counts=counts,
                       corpus_wer=sum(counts[k] for k in ("S", "D", "I")) / counts["N_ref"] if counts["N_ref"] else None,
                       text_latency=distribution([r["text_latency_ms"] for r in rows if r["text_latency_ms"] is not None]),
                       eof_text_changed=sum(r["eof_text_changed"] for r in rows),
                       eof_update_latency=distribution([r["eof_last_update_ms"] for r in rows if r["eof_last_update_ms"] is not None]))
    else:
        ok = [r for r in rows if r["replay_ok"]]
        hits = sum(r["hit"] for r in rows)
        summary.update(hits=hits, complete_rate=hits / planned if planned else None,
                       runtime_failed=sum(r["exit_code"] != 0 for r in rows),
                       replay_ok=len(ok), failed=planned - len(ok),
                       complete_rate_given_replay_ok=sum(r["hit"] for r in ok) / len(ok) if ok else None,
                       latency=distribution([r["latency_ms"] for r in rows if r["hit"]]),
                       **{key: sum(bool(r[key]) for r in rows) for key in
                          ("only_before", "only_after_eof", "never_observed", "protocol_anomalies")},
                       window_observed=sum(r["window_observed"] for r in rows),
                       no_hit_full_window=sum(r["complete_absent_full_window"] is True for r in rows),
                       incomplete_windows=sum(not r["window_observed"] for r in rows))
    report = {"schema": f"x2q-{metric}-score-v1", "summary": summary, "samples": rows}
    write_json(run / f"{metric}_scores.json", report)
    return report


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

    replay = sub.add_parser("replay", help="paced independent sessions with native traces")
    replay.add_argument("--root", type=Path, required=True)
    replay.add_argument("--run-id", required=True)
    replay.add_argument("--mode", choices=("dev", "smoke", "formal"), required=True)
    replay.add_argument("--url", default="ws://127.0.0.1:18011/v1/realtime")
    replay.add_argument("--model", default="x-square-robot/X2-Turn-4B-0812")
    for metric in ("asr", "complete"):
        score = sub.add_parser(f"score-{metric}", help=f"rescore frozen {metric} traces")
        score.add_argument("--run", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "replay":
        import asyncio
        result = asyncio.run(replay_run(args))
        summarize(result)
        plan = json.loads((Path(result["run"]) / "run.json").read_text())
        failed = any(json.loads((Path(result["run"]) / s["trace"]).read_text())["status"] != "ok"
                     for s in plan["samples"])
        if failed:
            raise SystemExit(1)
        return
    if args.command.startswith("score-"):
        summarize(score_run(args.run, args.command.removeprefix("score-")))
        return
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
