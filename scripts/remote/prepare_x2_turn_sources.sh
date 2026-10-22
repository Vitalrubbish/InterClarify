#!/usr/bin/env bash
# Materialize the pinned upstream checkouts the X2-Turn deployment needs.
#
# The scheduler nodes cannot reach github.com and the login-node git data
# channel is very slow, so both checkouts are partial clones limited to the
# files the deployment actually reads.  The applied sources stay identical to
# the pinned commits because the commits, blobs and patch are hash-checked.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
X2_TURN_COMMIT="67ec3fe49f1977ee3129f7eaed603c04d8ed23c5"
VLLM_COMMIT="b1388b1fbf5aaef47937fabe98931211684666a6"
VLLM_TAG="v0.19.1"
X2_URL="https://github.com/X-Square-Robot/X2-Turn"
VLLM_URL="https://github.com/vllm-project/vllm"
VLLM_DIR="$ROOT/source/vllm"
X2_DIR="$ROOT/source/X2-Turn"
mkdir -p "$ROOT/source" "$ROOT/env"

export GIT_TERMINAL_PROMPT=0
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

fetch_commit() {
  local dir="$1" url="$2" commit="$3"
  if [ ! -d "$dir/.git" ]; then
    mkdir -p "$dir"
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
  fi
  if ! git -C "$dir" cat-file -e "$commit^{commit}" 2>/dev/null; then
    log "fetching $url at $commit without blobs"
    git -C "$dir" fetch -q --filter=blob:none --depth 1 origin "$commit"
  fi
}

# Write sparse patterns directly instead of using `git sparse-checkout set`,
# which needs a checked-out HEAD.  A leading slash anchors each pattern.
sparse_checkout() {
  local dir="$1" commit="$2"
  shift 2
  git -C "$dir" config core.sparseCheckout true
  git -C "$dir" config core.sparseCheckoutCone false
  printf '%s\n' "$@" >"$dir/.git/info/sparse-checkout"
  git -C "$dir" checkout -f -q --detach "$commit"
}

log "X2-Turn $X2_TURN_COMMIT"
fetch_commit "$X2_DIR" "$X2_URL" "$X2_TURN_COMMIT"
sparse_checkout "$X2_DIR" "$X2_TURN_COMMIT" "/voxtral-realtime/"
[ "$(git -C "$X2_DIR" rev-parse HEAD)" = "$X2_TURN_COMMIT" ] || {
  echo "X2-Turn checkout does not match $X2_TURN_COMMIT" >&2; exit 1; }

PATCH="$X2_DIR/voxtral-realtime/patches/vllm-voxtral-mtp.patch"
[ -f "$PATCH" ] || { echo "missing overlay patch: $PATCH" >&2; exit 1; }
mapfile -t PATCHED < <(sed -n 's|^diff --git a/.* b/||p' "$PATCH")
[ "${#PATCHED[@]}" -eq 10 ] || { echo "Expected 10 patched files, found ${#PATCHED[@]}" >&2; exit 1; }

log "vLLM $VLLM_TAG ($VLLM_COMMIT)"
if [ -d "$VLLM_DIR/.git" ] && \
   [ "$(git -C "$VLLM_DIR" rev-parse HEAD 2>/dev/null || true)" != "$VLLM_COMMIT" ]; then
  rm -rf "$VLLM_DIR"
fi
if [ ! -d "$VLLM_DIR/.git" ]; then
  git clone -q --filter=blob:none --no-checkout --depth 1 --branch "$VLLM_TAG" \
    "$VLLM_URL" "$VLLM_DIR"
fi
[ "$(git -C "$VLLM_DIR" rev-parse HEAD)" = "$VLLM_COMMIT" ] || {
  echo "vLLM checkout does not match $VLLM_COMMIT" >&2; exit 1; }
[ "$(git -C "$VLLM_DIR" describe --tags --exact-match)" = "$VLLM_TAG" ] || {
  echo "vLLM checkout is not at tag $VLLM_TAG" >&2; exit 1; }
log "materializing ${#PATCHED[@]} patched files"
patterns=()
for rel in "${PATCHED[@]}"; do patterns+=("/$rel"); done
sparse_checkout "$VLLM_DIR" "$VLLM_COMMIT" "${patterns[@]}"
if [ -n "$(git -C "$VLLM_DIR" status --porcelain)" ]; then
  echo "vLLM sparse checkout is not clean" >&2; exit 1
fi
for rel in "${PATCHED[@]}"; do
  [ -f "$VLLM_DIR/$rel" ] || { echo "missing sparse file $rel" >&2; exit 1; }
done

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
    "x2_turn": {
        "path": x2_dir,
        "commit": x2_commit,
        "clone": "partial (blob:none) shallow sparse checkout: voxtral-realtime",
    },
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
