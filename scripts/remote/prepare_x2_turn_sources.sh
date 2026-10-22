#!/usr/bin/env bash
# Materialize the pinned upstream checkouts the X2-Turn deployment needs.
#
# The scheduler nodes cannot reach github.com, so this runs on the login node
# and writes a small source lock.  The vLLM checkout is a partial, sparse
# clone: only the ten files touched by the author overlay are materialized,
# which keeps the transfer small without changing the applied source.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
X2_TURN_COMMIT="67ec3fe49f1977ee3129f7eaed603c04d8ed23c5"
VLLM_COMMIT="b1388b1fbf5aaef47937fabe98931211684666a6"
VLLM_TAG="v0.19.1"
X2_URL="https://github.com/X-Square-Robot/X2-Turn"
VLLM_URL="https://github.com/vllm-project/vllm"
VLLM_DIR="$ROOT/source/vllm"
X2_DIR="$ROOT/source/X2-Turn"
OUTPUT="${X2_TURN_SOURCES_OUTPUT:-$ROOT/env}"
mkdir -p "$ROOT/source" "$OUTPUT"

export GIT_TERMINAL_PROMPT=0
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

if [ ! -d "$X2_DIR/.git" ]; then
  log "fetching X2-Turn $X2_TURN_COMMIT"
  git init -q "$X2_DIR"
  git -C "$X2_DIR" remote add origin "$X2_URL"
  git -C "$X2_DIR" fetch -q --depth 1 origin "$X2_TURN_COMMIT"
  git -C "$X2_DIR" checkout -q FETCH_HEAD
fi
[ "$(git -C "$X2_DIR" rev-parse HEAD)" = "$X2_TURN_COMMIT" ] || {
  echo "X2-Turn checkout does not match $X2_TURN_COMMIT" >&2; exit 1; }

PATCH="$X2_DIR/voxtral-realtime/patches/vllm-voxtral-mtp.patch"
mapfile -t PATCHED < <(sed -n 's|^diff --git a/.* b/||p' "$PATCH")
[ "${#PATCHED[@]}" -eq 10 ] || { echo "Expected 10 patched files, found ${#PATCHED[@]}" >&2; exit 1; }

if [ ! -d "$VLLM_DIR/.git" ]; then
  log "fetching vLLM $VLLM_TAG ($VLLM_COMMIT) without blobs"
  rm -rf "$VLLM_DIR"
  git clone -q --filter=blob:none --no-checkout --depth 1 --branch "$VLLM_TAG" \
    "$VLLM_URL" "$VLLM_DIR"
fi
[ "$(git -C "$VLLM_DIR" rev-parse HEAD)" = "$VLLM_COMMIT" ] || {
  echo "vLLM checkout does not match $VLLM_COMMIT" >&2; exit 1; }
[ "$(git -C "$VLLM_DIR" describe --tags --exact-match)" = "$VLLM_TAG" ] || {
  echo "vLLM checkout is not at tag $VLLM_TAG" >&2; exit 1; }
log "materializing ${#PATCHED[@]} patched files"
git -C "$VLLM_DIR" sparse-checkout init --no-cone
git -C "$VLLM_DIR" sparse-checkout set --no-cone "${PATCHED[@]}"
git -C "$VLLM_DIR" checkout -q "$VLLM_TAG"
if [ -n "$(git -C "$VLLM_DIR" status --porcelain)" ]; then
  echo "vLLM sparse checkout is not clean" >&2; exit 1
fi

python3 - "$ROOT" "$X2_DIR" "$VLLM_DIR" "$X2_TURN_COMMIT" \
  "$VLLM_COMMIT" "$VLLM_TAG" "$PATCH" "${PATCHED[@]}" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root, x2_dir, vllm_dir, x2_commit, vllm_commit, tag, patch = sys.argv[1:8]
patched = sys.argv[8:]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


lock = {
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "x2_turn": {"path": x2_dir, "commit": x2_commit},
    "vllm": {
        "path": vllm_dir,
        "commit": vllm_commit,
        "tag": tag,
        "clone": "partial (blob:none) shallow sparse checkout",
        "sparse_files": {name: sha256(Path(vllm_dir) / name) for name in patched},
    },
    "overlay_patch": {"path": patch, "sha256": sha256(Path(patch))},
}
target = Path(root) / "env" / "x2_turn_source_lock.json"
temporary = target.with_name(target.name + ".part")
temporary.write_text(json.dumps(lock, indent=2) + "\n")
os.replace(temporary, target)
print(f"wrote {target}")
PY
log "source checkouts ready"
