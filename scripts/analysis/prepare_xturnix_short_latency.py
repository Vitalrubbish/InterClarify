"""Freeze a reviewed cohort and optionally normalize its original audio."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from compare_xturnix_latency import file_sha, partition

REVISION = "ca9d98a9686b920a2d8c9eb984224ba9be74e4dd"


def read_bounded(url: str, limit: int) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                value = response.read(limit + 1)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    if len(value) > limit:
        raise ValueError("download exceeds byte limit")
    return value


def prepare(inputs: Path, labels: Path, config_path: Path, output: Path,
            download_audio: bool = False, audio_cache: Path | None = None) -> dict:
    config = json.loads(config_path.read_text())
    prepared = json.loads((inputs / "prepare_summary.json").read_text())
    if file_sha(inputs / "source_metadata.json") != prepared["source_metadata_sha256"]:
        raise ValueError("source metadata digest mismatch")
    if file_sha(inputs / "dev.json.gz") != prepared["inputs"]["dev"]["sha256"]:
        raise ValueError("development input digest mismatch")
    metadata = {r["id"]: r for r in json.loads((inputs / "source_metadata.json").read_text())}
    observations = json.loads(gzip.decompress((inputs / "dev.json.gz").read_bytes()))
    history = {r["turn_id"]: r["messages"][:-1] for r in observations}
    selected = {r["turn_id"]: r["category"] for r in csv.DictReader(labels.open())
                if r["included"] == "True" and r["category"] != "slot_fragment"}
    if len(selected) != 45 or not set(selected) <= set(history):
        raise ValueError("expected frozen 45-turn development cohort")
    audio_urls, ledger = {}, []
    for offset in range(0, 400, 100):
        url = ("https://datasets-server.huggingface.co/rows?"
               "dataset=livekit%2Feot-bench-data&config=en&split=validation"
               f"&offset={offset}&length=100")
        blob = read_bounded(url, 8 * 1024 ** 2)
        page = json.loads(blob)
        if page["partial"] or page["num_rows_total"] != 400:
            raise ValueError("source population changed")
        for entry in page["rows"]:
            row = dict(entry["row"])
            audio = row.pop("audio")
            if entry["truncated_cells"] or metadata.get(row["id"]) != row:
                raise ValueError("metadata no longer matches frozen revision")
            if row["id"] in selected:
                if not audio or f"/{REVISION}/" not in audio[0]["src"]:
                    raise ValueError("audio revision mismatch")
                audio_urls[row["id"]] = audio[0]["src"]
        ledger.append({"url": url, "bytes": len(blob),
                       "sha256": hashlib.sha256(blob).hexdigest()})
    output.mkdir(parents=True, exist_ok=False)
    (output / "audio").mkdir()
    (output / "source_audio").mkdir()
    cases, downloaded, fetched, reused = [], 0, 0, 0
    for turn_id in sorted(selected):
        source = metadata[turn_id]
        case = {"turn_id": turn_id,
                "conversation_id": turn_id.rsplit("__user_turn_", 1)[0],
                "category": selected[turn_id], "history": history[turn_id],
                "word_end": source["words"][-1]["end"],
                "silence_start": source["silence_spans"][-1]["start"],
                "source_duration": source["duration"], "audio_url": audio_urls[turn_id],
                "audio_path": f"audio/{turn_id}.wav"}
        case["partition"] = partition(case["conversation_id"], config)
        if download_audio:
            import numpy as np
            import soundfile as sf
            from scipy.signal import resample_poly
            from math import gcd

            cached = audio_cache / "source_audio" / f"{turn_id}.bin" if audio_cache else None
            if cached and cached.exists():
                if cached.stat().st_size > 64 * 1024 ** 2:
                    raise ValueError("cached audio exceeds byte limit")
                data = cached.read_bytes()
                reused += 1
            else:
                data = read_bounded(case["audio_url"], 64 * 1024 ** 2)
                fetched += len(data)
            downloaded += len(data)
            if downloaded > config["max_audio_bytes"]:
                raise ValueError("audio asset budget exceeded")
            raw_path = output / "source_audio" / f"{turn_id}.bin"
            if cached and cached.exists():
                try:
                    os.link(cached, raw_path)
                except OSError:
                    raw_path.write_bytes(data)
            else:
                raw_path.write_bytes(data)
            samples, rate = sf.read(raw_path, dtype="float32", always_2d=True)
            if not np.isfinite(samples).all() or abs(len(samples) / rate - source["duration"]) > .15:
                raise ValueError("invalid source audio or duration mismatch")
            mono = samples.mean(axis=1)
            if rate != 16000:
                factor = gcd(rate, 16000)
                mono = resample_poly(mono, 16000 // factor, rate // factor)
            target = output / case["audio_path"]
            sf.write(target, np.clip(mono, -1, 1), 16000, subtype="PCM_16")
            normalized_bytes = sum(c.get("audio_bytes", 0) for c in cases) + target.stat().st_size
            if downloaded + normalized_bytes > config["max_audio_bytes"]:
                raise ValueError("source and normalized audio exceed combined asset budget")
            case.update({"source_audio_sha256": file_sha(raw_path),
                         "audio_sha256": file_sha(target), "audio_bytes": target.stat().st_size})
        cases.append(case)
    manifest = {"schema": "xtx014-short-latency-inputs-v1", "source_revision": REVISION,
                "config_sha256": file_sha(config_path), "labels_sha256": file_sha(labels),
                "source_metadata_sha256": prepared["source_metadata_sha256"],
                "audio_downloaded": download_audio, "reused_source_audio_files": reused,
                "network_audio_bytes": fetched, "request_ledger": ledger, "cases": cases}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"turns": len(cases), "source_audio_bytes": downloaded,
                      "network_audio_bytes": fetched, "reused_source_audio_files": reused,
                      "partition_counts": {p: sum(c["partition"] == p for c in cases)
                                           for p in ("calibration", "evaluation")}}, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-audio", action="store_true")
    parser.add_argument("--audio-cache", type=Path)
    args = parser.parse_args()
    prepare(args.inputs, args.labels, args.config, args.output, args.download_audio, args.audio_cache)


if __name__ == "__main__":
    main()
