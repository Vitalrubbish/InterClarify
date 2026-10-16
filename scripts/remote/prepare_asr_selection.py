"""Pin and download the models and shared FLEURS ASR evaluation subset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, snapshot_download


MODELS = {
    "nemotron_en": "nvidia/nemotron-speech-streaming-en-0.6b",
    "nemotron_multi": "nvidia/nemotron-3.5-asr-streaming-0.6b",
    "kyutai": "kyutai/stt-1b-en_fr",
    "alignment": "facebook/wav2vec2-base-960h",
}


def digest(path: Path) -> str:
    """Hash a file without loading model weights into memory."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def prepare_models(root: Path, candidate: str | None = None) -> None:
    """Fetch only the selected backend artifacts at immutable revisions."""
    lock_path = root / (f"models.{candidate}.lock.json" if candidate else "models.lock.json")
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    api = HfApi()
    for name, repo in MODELS.items():
        if candidate and name != candidate:
            continue
        revision = lock.get(name, {}).get("revision") or api.model_info(repo).sha
        destination = root / "models" / name
        print("download", name, revision, flush=True)
        snapshot_download(
            repo, revision=revision, local_dir=destination, max_workers=4,
            ignore_patterns=["*.gguf", "*.nemo", "*.onnx", "*.bin", "figures/*"],
        )
        lock[name] = {"repo": repo, "revision": revision, "path": str(destination)}
        # Persist each successful download so an interrupted rerun keeps its pin.
        write_json(lock_path, lock)
        if name == "kyutai":
            config = json.loads((destination / "config.json").read_text())
            mimi_name = config.get("mimi_name", "")
            if mimi_name and (destination / mimi_name).is_file():
                continue
            mimi_repo = "kyutai/mimi"
            mimi_revision = lock.get("mimi", {}).get("revision") or api.model_info(mimi_repo).sha
            mimi_dir = root / "models" / "mimi"
            snapshot_download(mimi_repo, revision=mimi_revision, local_dir=mimi_dir,
                              allow_patterns=["*.json", "*.safetensors", "README.md", "LICENSE*"],
                              max_workers=4)
            lock["mimi"] = {"repo": mimi_repo, "revision": mimi_revision, "path": str(mimi_dir)}
            write_json(lock_path, lock)
    for item in lock.values():
        directory = Path(item["path"])
        item["files"] = {str(p.relative_to(directory)): digest(p)
                         for p in sorted(directory.rglob("*"))
                         if p.is_file() and ".cache" not in p.parts}
    write_json(lock_path, lock)


def prepare_data(root: Path, count: int) -> None:
    """Select test WAVs by hashed filename and keep a separate dev warmup."""
    import soundfile as sf

    destination = root / "dataset"
    destination.mkdir(exist_ok=True)
    repo = "google/fleurs"
    lock_path = destination / "dataset.lock.json"
    old = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    revision = old.get("revision") or HfApi().dataset_info(repo).sha
    write_json(lock_path, {"repo": repo, "revision": revision, "count": count})
    samples = []
    for split, limit in (("test", count), ("dev", 1)):
        tsv = hf_hub_download(repo, f"data/en_us/{split}.tsv", repo_type="dataset", revision=revision)
        with open(tsv, newline="") as stream:
            rows = list(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
        rows.sort(key=lambda row: hashlib.sha256(row[1].encode()).hexdigest())
        selected = rows[:limit]
        archive_path = hf_hub_download(repo, f"data/en_us/audio/{split}.tar.gz",
                                       repo_type="dataset", revision=revision)
        audio_dir = destination / split
        audio_dir.mkdir(exist_ok=True)
        with tarfile.open(archive_path) as archive:
            members = {Path(m.name).name: m for m in archive.getmembers() if m.isfile()}
            for row in selected:
                name = row[1]
                if Path(name).name != name or name not in members:
                    raise ValueError(f"Invalid or missing audio member: {name}")
                audio_path = audio_dir / name
                with archive.extractfile(members[name]) as source, audio_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                info = sf.info(audio_path)
                samples.append({"sample_id": f"{split}/{name}", "split": split,
                                "path": str(audio_path), "sha256": digest(audio_path),
                                "reference": row[2], "dataset_normalized_reference": row[3],
                                "sentence_id": row[0], "gender": row[6],
                                "sample_rate": info.samplerate, "frames": info.frames,
                                "duration_seconds": info.duration})
        print("dataset", split, len(selected), flush=True)
    write_json(destination / "manifest.json", {"repo": repo, "revision": revision,
               "selection": "SHA256(filename), ascending", "samples": samples})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--only", choices=["models", "data", "all"], default="all")
    parser.add_argument("--candidate", choices=list(MODELS))
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.only in ("data", "all"):
        prepare_data(args.root, args.count)
    if args.only in ("models", "all"):
        prepare_models(args.root, args.candidate)


if __name__ == "__main__":
    main()
