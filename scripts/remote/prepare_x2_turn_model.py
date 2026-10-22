"""Fetch, verify and export the pinned X2-Turn checkpoint for vLLM serving.

The deployment work item needs one frozen Hugging Face revision, its file
hashes, the exported vLLM directory and the transcription delay that the
service will actually apply.  All of that is written to
``<root>/env/x2_turn_model_lock.json`` so later replay and scoring stages do
not depend on whatever the model hub serves that day.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MODEL_REPO = "x-square-robot/X2-Turn-4B-0812"
MODEL_REVISION = "49c62a9b1170f2ab5168e763b84c2ac5c6b5e1ee"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"
ALLOW_PATTERNS = [
    "model.safetensors",
    "params.json",
    "tekken.json",
    "config.json",
    "generation_config.json",
    "processor_config.json",
    "LICENSE",
    "NOTICE",
    "README.md",
]
MODEL_DIR_NAME = "X2-Turn-4B-0812"
EXPORT_DIR_NAME = "X2-Turn-4B-0812-vllm"
USER_AGENT = "interclarify-x2-turn/1.0 (offline deployment)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def tree_metadata(endpoint: str, repo: str, revision: str) -> dict[str, dict[str, object]]:
    """Return path -> {size, lfs_sha256} for one pinned revision."""
    url = f"{endpoint.rstrip('/')}/api/models/{repo}/tree/{revision}?recursive=true"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        entries = json.load(response)
    files: dict[str, dict[str, object]] = {}
    for entry in entries:
        if entry.get("type") != "file":
            continue
        lfs = entry.get("lfs") or {}
        files[entry["path"]] = {
            "size": int(entry["size"]),
            "lfs_sha256": lfs.get("oid"),
        }
    return files


def compute_delay(config: dict, tekken: dict) -> dict[str, object]:
    """Derive the 80 ms-grid transcription delay and cross-check both sources."""
    audio = tekken.get("audio") or {}
    encoding = audio.get("audio_encoding_config") or {}
    delay_tokens = int(config["default_num_delay_tokens"])
    audio_length_per_tok = int(config["audio_length_per_tok"])
    hop_length = int(encoding["hop_length"])
    sample_rate = int(audio["sampling_rate"])
    per_token_ms = 1000.0 * audio_length_per_tok * hop_length / sample_rate
    computed_ms = round(delay_tokens * per_token_ms)
    declared_ms = int(audio["transcription_delay_ms"])
    if computed_ms != declared_ms:
        raise ValueError(
            "delay mismatch: config.json implies "
            f"{computed_ms} ms but tekken.json declares {declared_ms} ms"
        )
    return {
        "delay_tokens": delay_tokens,
        "audio_length_per_tok": audio_length_per_tok,
        "hop_length": hop_length,
        "sample_rate": sample_rate,
        "ms_per_token": per_token_ms,
        "transcription_delay_ms": computed_ms,
        "declared_transcription_delay_ms": declared_ms,
        "config_json_consistent": True,
    }


def verify_snapshot(
    model_dir: Path,
    expected: dict[str, dict[str, object]],
    names: list[str] | None = None,
) -> list[dict[str, object]]:
    """Check sizes for every allowed file and hashes for LFS blobs."""
    results: list[dict[str, object]] = []
    for name in names or ALLOW_PATTERNS:
        path = model_dir / name
        if not path.exists():
            raise FileNotFoundError(f"missing expected checkpoint file: {path}")
        info = expected.get(name)
        if info is None:
            raise FileNotFoundError(f"{name} is not part of the pinned revision")
        size = path.stat().st_size
        if size != info["size"]:
            raise ValueError(f"{name}: size {size} != expected {info['size']}")
        actual = sha256_file(path)
        expected_sha = info.get("lfs_sha256")
        if expected_sha and actual != expected_sha:
            raise ValueError(f"{name}: sha256 {actual} != expected {expected_sha}")
        results.append(
            {
                "path": name,
                "size": size,
                "sha256": actual,
                "expected_sha256": expected_sha,
                "verified_sha256": bool(expected_sha),
            }
        )
    return results


def download(endpoint: str, revision: str, target: Path, events: Path) -> None:
    from huggingface_hub import snapshot_download

    started = time.monotonic()
    snapshot_download(
        repo_id=MODEL_REPO,
        revision=revision,
        local_dir=str(target),
        allow_patterns=ALLOW_PATTERNS,
        endpoint=endpoint,
    )
    elapsed = round(time.monotonic() - started, 1)
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at": utc_now(),
                    "event": "download",
                    "endpoint": endpoint,
                    "revision": revision,
                    "seconds": elapsed,
                }
            )
            + "\n"
        )


def export_for_vllm(source_dir: Path, target_dir: Path, x2_checkout: Path) -> dict[str, object]:
    tool = (
        x2_checkout
        / "voxtral-realtime/integrations/vllm/tools/export_mtp_for_vllm.py"
    )
    if not tool.is_file():
        raise FileNotFoundError(f"missing export tool: {tool}")
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, str(tool), "--src", str(source_dir), "--dst", str(target_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "vLLM export failed:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    weights = target_dir / "consolidated.safetensors"
    if not weights.is_file():
        raise FileNotFoundError(f"export produced no weights: {weights}")
    exported = {}
    for path in sorted(target_dir.iterdir()):
        if path.is_file():
            exported[path.name] = {
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return {
        "seconds": round(time.monotonic() - started, 1),
        "tool": str(tool),
        "tool_sha256": sha256_file(tool),
        "files": exported,
        "stdout": completed.stdout.strip().splitlines(),
    }


def inspect_tokenizer_delay(model_dir: Path) -> dict[str, object]:
    """Read the delay exactly where the served model reads it."""
    try:
        from mistral_common.tokens.tokenizers.mistral import MistralTokenizer

        tokenizer = MistralTokenizer.from_file(str(model_dir / "tekken.json"))
        audio_config = tokenizer.instruct.audio_encoder.audio_config
        result: dict[str, object] = {
            "source": "mistral_common tekken.json audio_config",
            "num_delay_tokens": int(audio_config.get_num_delay_tokens()),
        }
        for attribute in ("transcription_delay_ms", "sampling_rate", "frame_rate"):
            if hasattr(audio_config, attribute):
                result[attribute] = getattr(audio_config, attribute)
        return result
    except Exception as error:  # pragma: no cover - depends on installed version
        return {"source": "mistral_common tekken.json audio_config", "error": repr(error)}


def prepare(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    model_dir = root / "models" / MODEL_DIR_NAME
    export_dir = root / "models" / EXPORT_DIR_NAME
    lock_path = root / "env" / "x2_turn_model_lock.json"
    events = root / "logs" / "x2_turn_model_events.jsonl"
    x2_checkout = root / "source" / "x2_turn_sources" / "x2"
    if not (x2_checkout / "voxtral-realtime").is_dir():
        raise FileNotFoundError(
            f"missing pinned source bundle at {x2_checkout}; run the environment setup first"
        )

    expected = tree_metadata(args.endpoint, MODEL_REPO, args.revision)
    model_dir.mkdir(parents=True, exist_ok=True)
    download(args.endpoint, args.revision, model_dir, events)
    files = verify_snapshot(model_dir, expected)

    config = json.loads((model_dir / "config.json").read_text())
    tekken = json.loads((model_dir / "tekken.json").read_text())
    delay = compute_delay(config, tekken)
    tokenizer_delay = inspect_tokenizer_delay(model_dir)
    if tokenizer_delay.get("num_delay_tokens") != delay["delay_tokens"]:
        raise ValueError(f"tokenizer delay mismatch: {tokenizer_delay} vs {delay}")

    export = export_for_vllm(model_dir, export_dir, x2_checkout)
    if not (export_dir / "params.json").is_file():
        raise FileNotFoundError("exported directory has no params.json")

    lock = {
        "created_at": utc_now(),
        "repo": MODEL_REPO,
        "revision": args.revision,
        "endpoint": args.endpoint,
        "model_dir": str(model_dir),
        "export_dir": str(export_dir),
        "files": files,
        "delay": delay,
        "tokenizer_delay": tokenizer_delay,
        "export": export,
        "source_checkout": str(x2_checkout),
    }
    write_json(lock_path, lock)
    print(
        json.dumps(
            {
                "lock": str(lock_path),
                "revision": lock["revision"],
                "delay_ms": delay["transcription_delay_ms"],
                "files": len(files),
                "exported": sorted(export["files"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    lock_path = root / "env" / "x2_turn_model_lock.json"
    lock = json.loads(lock_path.read_text())
    if lock["revision"] != args.revision:
        raise ValueError(
            f"lock revision {lock['revision']} != requested {args.revision}"
        )
    expected = tree_metadata(args.endpoint, MODEL_REPO, args.revision)
    model_dir = Path(lock["model_dir"])
    files = verify_snapshot(model_dir, expected)
    for item in lock["files"]:
        if not any(entry["path"] == item["path"] for entry in files):
            raise ValueError(f"lock lists a file that is not in the pinned revision: {item}")
    for name, info in lock["export"]["files"].items():
        path = Path(lock["export_dir"]) / name
        if sha256_file(path) != info["sha256"]:
            raise ValueError(f"exported file hash drift: {path}")
    print(json.dumps({"verified": True, "files": len(files)}, indent=2))
    return 0


def inspect(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    lock = json.loads((root / "env" / "x2_turn_model_lock.json").read_text())
    print(
        json.dumps(
            {
                "revision": lock["revision"],
                "delay": lock["delay"],
                "tokenizer_delay": inspect_tokenizer_delay(Path(lock["model_dir"])),
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("HF_ENDPOINT", DEFAULT_HF_ENDPOINT),
    )
    parser.add_argument("--revision", default=MODEL_REVISION)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="download, verify and export")
    prepare_parser.set_defaults(func=prepare)
    verify_parser = sub.add_parser("verify", help="recheck an existing lock")
    verify_parser.set_defaults(func=verify)
    inspect_parser = sub.add_parser("inspect", help="print the frozen delay")
    inspect_parser.set_defaults(func=inspect)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
