"""Build the small source bundle that the offline deployment host needs.

The scheduler nodes cannot reach github.com and the login-node git channel is
far too slow for a full checkout, so this runs on a machine with GitHub access
and emits a compact archive:

* the ten pinned vLLM files touched by the author overlay (pre-patch state),
* the overlay patch,
* the turn-head helper and the export tool from the pinned X2-Turn checkout.

The archive manifest records the git blob hashes from the overlay patch and
the X2-Turn commit, so the offline host can prove every file matches the
pinned revision without any network access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

VLLM_COMMIT = "b1388b1fbf5aaef47937fabe98931211684666a6"
VLLM_TAG = "v0.19.1"
X2_TURN_COMMIT = "67ec3fe49f1977ee3129f7eaed603c04d8ed23c5"
X2_FILES = [
    "voxtral-realtime/patches/vllm-voxtral-mtp.patch",
    "voxtral-realtime/integrations/vllm/vllm/model_executor/models/voxtral_mtp_utils.py",
    "voxtral-realtime/integrations/vllm/tools/export_mtp_for_vllm.py",
]
BUNDLE_NAME = "x2_turn_sources"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    """Git blob id of a working-tree file, independent of any repository."""
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - git object id


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def patch_entries(patch: Path) -> list[tuple[str, str, str]]:
    text = patch.read_text()
    entries = re.findall(
        r"^diff --git a/(\S+) b/\S+\nindex ([0-9a-f]+)\.\.([0-9a-f]+)", text, re.M
    )
    if len(entries) != 10:
        raise ValueError(f"expected 10 patched files, found {len(entries)}")
    return [(path, pre, post) for path, pre, post in entries]


def build(vllm: Path, x2: Path, output: Path) -> dict[str, object]:
    if git(vllm, "rev-parse", "HEAD") != VLLM_COMMIT:
        raise SystemExit(f"{vllm} is not at {VLLM_COMMIT}")
    if git(vllm, "describe", "--tags", "--exact-match") != VLLM_TAG:
        raise SystemExit(f"{vllm} is not tagged {VLLM_TAG}")
    if git(x2, "rev-parse", "HEAD") != X2_TURN_COMMIT:
        raise SystemExit(f"{x2} is not at {X2_TURN_COMMIT}")

    patch_rel = X2_FILES[0]
    patch = x2 / patch_rel
    entries = patch_entries(patch)

    work = output / BUNDLE_NAME
    if work.exists():
        shutil.rmtree(work)
    (work / "vllm").mkdir(parents=True)
    (work / "x2").mkdir()

    files: dict[str, dict[str, str]] = {}
    for rel, pre, post in entries:
        source = vllm / rel
        if not source.is_file():
            raise SystemExit(f"missing pinned vLLM file {rel}; materialize it first")
        actual = git_blob_sha1(source)
        if actual != pre:
            raise SystemExit(f"{rel}: blob {actual} != patch pre-image {pre}")
        target = work / "vllm" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files[rel] = {
            "git_blob_sha1_pre": pre,
            "git_blob_sha1_post": post,
            "sha256_pre": sha256_file(source),
        }

    x2_files: dict[str, dict[str, str]] = {}
    for rel in X2_FILES:
        source = x2 / rel
        if not source.is_file():
            raise SystemExit(f"missing pinned X2-Turn file {rel}")
        target = work / "x2" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        x2_files[rel] = {
            "git_blob_sha1": git_blob_sha1(source),
            "sha256": sha256_file(source),
            "tracked_blob_sha1": git(x2, "rev-parse", f"HEAD:{rel}"),
        }
        if x2_files[rel]["git_blob_sha1"] != x2_files[rel]["tracked_blob_sha1"]:
            raise SystemExit(f"{rel}: working tree differs from the pinned commit")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "offline materialization of the pinned X2-Turn vLLM overlay sources",
        "vllm": {"commit": VLLM_COMMIT, "tag": VLLM_TAG, "files": files},
        "x2_turn": {"commit": X2_TURN_COMMIT, "files": x2_files},
        "overlay_patch": {
            "path": f"x2/{patch_rel}",
            "sha256": sha256_file(patch),
            "git_blob_sha1": git_blob_sha1(patch),
        },
    }
    (work / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )

    archive = output / f"{BUNDLE_NAME}.tar.gz"
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz", compresslevel=9) as tar:
        for path in sorted(work.rglob("*")):
            tar.add(path, arcname=str(path.relative_to(output)))
    manifest["archive"] = {
        "name": archive.name,
        "size": archive.stat().st_size,
        "sha256": sha256_file(archive),
    }
    (output / f"{BUNDLE_NAME}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vllm-checkout", type=Path, required=True)
    parser.add_argument("--x2-turn-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = build(
        args.vllm_checkout.resolve(), args.x2_turn_checkout.resolve(), args.output
    )
    print(
        json.dumps(
            {
                "archive": manifest["archive"],
                "files": {
                    "vllm": len(manifest["vllm"]["files"]),
                    "x2_turn": len(manifest["x2_turn"]["files"]),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
