"""Freeze FDB turn-taking inputs and offline-only boundary annotations."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--fdb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads((args.root / "dataset/manifest.json").read_text())
    samples = [next(r for r in original["samples"] if r["split"] == "dev")]
    for sample_id in ("1", "10", "100", "101", "102"):
        directory = args.fdb / "candor_turn_taking" / sample_id
        audio = directory / "input.wav"
        metadata = directory / "turn_taking.json"
        annotations = json.loads(metadata.read_text())
        intervals = [a["timestamp"] for a in annotations if a["text"] == "[TURN-TAKING]"]
        if len(intervals) != 1:
            raise ValueError(f"Expected one turn boundary: {sample_id}")
        info = sf.info(audio)
        if info.samplerate != 16000 or info.channels != 1:
            raise ValueError(f"Expected mono 16 kHz: {audio}")
        samples.append({"sample_id": f"fdb/candor_turn_taking/{sample_id}", "split": "test",
                        "path": str(audio), "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                        "reference": "", "reference_source": "unavailable; excluded from WER",
                        "duration_seconds": info.duration, "sample_rate": info.samplerate,
                        "frames": info.frames, "boundary_interval": intervals[0],
                        "boundary_seconds": intervals[0][1],
                        "annotation_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"repo": "Full-Duplex-Bench v1.0 candor_turn_taking",
        "revision": "frozen audio and annotation SHA256 in samples", "samples": samples}, indent=2))


if __name__ == "__main__":
    main()
