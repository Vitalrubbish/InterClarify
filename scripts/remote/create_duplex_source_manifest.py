#!/usr/bin/env python3
"""Create a deterministic source manifest for a remote Duplex A4 job."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def git_value(root: Path, *args: str) -> str | None:
    """Return one git value, or None when the checkout is unavailable."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def tracked_files(root: Path) -> list[Path]:
    """Select runtime, test, and configuration files used by A4."""
    patterns = (
        "scripts/remote/duplex_model_service.py",
        "scripts/remote/duplex_runtime_smoke.py",
        "scripts/remote/duplex_a4_replay.py",
        "scripts/remote/xtalk_link_check.py",
        "scripts/remote/x2_asr_service.py",
        "scripts/remote/setup_x2_asr_env.sh",
        "configs/xtalk_duplex_x2_runtime.json",
        "tests/test_x2_asr_service.py",
        "scripts/remote/run_xtalk_round1.py",
        "scripts/remote/run_xtalk_duplex_a4_node_job.sh",
        "xtalk/src/xtalk/**/*.py",
        "xtalk/tests/**/*.py",
        "configs/xtalk_round1.yaml",
        "scripts/remote/create_duplex_source_manifest.py",
        "scripts/remote/compact_a4_report.py",
        "scripts/remote/submit_xtalk_duplex_a4_job.sh",
        "scripts/remote/moss_tts_patch.py",
        "tests/test_duplex_a4_replay.py",
        "tests/test_duplex_model_service.py",
        "tests/test_moss_tts_patch.py",
    )
    files: set[Path] = set()
    for pattern in patterns:
        candidate = root / pattern
        if candidate.is_file():
            files.add(candidate)
        else:
            files.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(files)


def build_manifest(root: Path) -> dict:
    """Hash selected files and record both git commits and dirty state."""
    files = tracked_files(root)
    if not files:
        raise ValueError(f"no A4 source files found under {root}")
    file_hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    xtalk_root = root / "xtalk"
    snapshot_payload = "\n".join(
        f"{name} {digest}" for name, digest in file_hashes.items()
    ).encode()
    return {
        "schema_version": 1,
        "files": file_hashes,
        "interclarify_commit": git_value(root, "rev-parse", "HEAD"),
        "xtalk_commit": git_value(xtalk_root, "rev-parse", "HEAD"),
        "xtalk_parent": git_value(xtalk_root, "rev-parse", "HEAD^"),
        "interclarify_dirty": bool(git_value(root, "status", "--porcelain")),
        "xtalk_dirty": bool(git_value(xtalk_root, "status", "--porcelain")),
        "snapshot": hashlib.sha256(snapshot_payload).hexdigest(),
    }


def main() -> None:
    """Write a source_manifest.json file and print its snapshot digest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / "source_manifest.json").resolve()
    manifest = build_manifest(root)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "snapshot": manifest["snapshot"], "files": len(manifest["files"])}))


if __name__ == "__main__":
    main()
