#!/usr/bin/env bash
# Install the pinned X2-Turn vLLM overlay into an isolated conda environment.
#
# vLLM is installed from the official 0.19.1 wheel instead of a local source
# build: a source build needs a full CUDA toolchain and far more than the
# 4 CPU / 16 GiB install budget of this work item.  The wheel and the pinned
# source commit are compared file by file before the overlay is applied, and
# every hash is written to the environment lock.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
OUTPUT="${X2_TURN_SETUP_OUTPUT:?set a new setup output directory}"
CONDA="${X2_TURN_CONDA:-$HOME/miniconda3/bin/conda}"
ENV_PREFIX="${X2_TURN_CONDA_ENV:-$HOME/miniconda3/envs/interclarify-x2-turn-vllm}"
CONDA_MIRROR="${X2_TURN_CONDA_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"
PIP_INDEX="${X2_TURN_PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
X2_TURN_COMMIT="67ec3fe49f1977ee3129f7eaed603c04d8ed23c5"
VLLM_COMMIT="b1388b1fbf5aaef47937fabe98931211684666a6"
VLLM_TAG="v0.19.1"

[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
mkdir -p "$OUTPUT" "$ROOT/env" "$ROOT/source" "$ROOT/logs"

export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 MAX_JOBS=4
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PIP_NO_CACHE_DIR=1
export GIT_TERMINAL_PROMPT=0

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

capacity() {
  df -B1 --output=avail "$ROOT" | tail -1 | awk '{printf "%.1f", $1/1024/1024/1024}'
}

FREE_GIB="$(capacity)"
log "free disk on $ROOT: ${FREE_GIB} GiB"
awk -v free="$FREE_GIB" 'BEGIN { if (free < 100) { print "Need >=100 GiB free"; exit 1 } }'

# 1. Isolated conda environment.  The active component environments are never
# reused or modified.
if [ ! -x "$ENV_PREFIX/bin/python" ]; then
  log "creating conda environment $ENV_PREFIX"
  "$CONDA" create -y -p "$ENV_PREFIX" --override-channels -c "$CONDA_MIRROR" \
    python=3.11 pip >"$OUTPUT/conda_create.log" 2>&1
else
  log "reusing conda environment $ENV_PREFIX"
fi
PY="$ENV_PREFIX/bin/python"
"$PY" -V >"$OUTPUT/python_version.txt"

# 2. Official vLLM wheel plus the runtime pieces the service and probes need.
if "$PY" -c 'import vllm, sys; sys.exit(0 if vllm.__version__ == "0.19.1" else 1)' 2>/dev/null; then
  log "vllm 0.19.1 already installed in $ENV_PREFIX"
else
  log "installing vllm==0.19.1 from $PIP_INDEX"
  "$PY" -m pip install --index-url "$PIP_INDEX" \
    "vllm==0.19.1" mistral-common soundfile websockets huggingface_hub \
    >"$OUTPUT/pip_install.log" 2>&1
fi
"$PY" -m pip freeze >"$OUTPUT/pip_freeze.txt"

# 3. Pinned upstream checkouts.  Only the two repositories this work item
# needs are cloned, shallow and single committed.
VLLM_DIR="$ROOT/source/vllm"
X2_DIR="$ROOT/source/X2-Turn"
if [ ! -d "$VLLM_DIR/.git" ]; then
  git init -q "$VLLM_DIR"
  git -C "$VLLM_DIR" remote add origin https://github.com/vllm-project/vllm
fi
if [ "$(git -C "$VLLM_DIR" rev-parse HEAD 2>/dev/null || true)" != "$VLLM_COMMIT" ]; then
  log "fetching vLLM $VLLM_TAG ($VLLM_COMMIT)"
  git -C "$VLLM_DIR" fetch -q --depth 1 origin \
    "refs/tags/$VLLM_TAG:refs/tags/$VLLM_TAG"
  git -C "$VLLM_DIR" checkout -q "$VLLM_TAG"
fi
if [ ! -d "$X2_DIR/.git" ]; then
  git init -q "$X2_DIR"
  git -C "$X2_DIR" remote add origin https://github.com/X-Square-Robot/X2-Turn
fi
if [ "$(git -C "$X2_DIR" rev-parse HEAD 2>/dev/null || true)" != "$X2_TURN_COMMIT" ]; then
  log "fetching X2-Turn $X2_TURN_COMMIT"
  git -C "$X2_DIR" fetch -q --depth 1 origin "$X2_TURN_COMMIT"
  git -C "$X2_DIR" checkout -q FETCH_HEAD
fi
[ "$(git -C "$VLLM_DIR" rev-parse HEAD)" = "$VLLM_COMMIT" ] || {
  echo "vLLM checkout does not match $VLLM_COMMIT" >&2; exit 1; }
[ "$(git -C "$X2_DIR" rev-parse HEAD)" = "$X2_TURN_COMMIT" ] || {
  echo "X2-Turn checkout does not match $X2_TURN_COMMIT" >&2; exit 1; }

# 4. The overlay only touches Python modules.  Refuse to continue if the wheel
# and the pinned commit disagree on any of those files, otherwise "0.19.1 +
# overlay" would silently describe a different baseline.
SITE="$("$PY" -c 'import vllm, pathlib; print(pathlib.Path(vllm.__file__).parent)')"
PATCH="$X2_DIR/voxtral-realtime/patches/vllm-voxtral-mtp.patch"
mapfile -t PATCHED < <(sed -n 's|^diff --git a/.* b/||p' "$PATCH")
[ "${#PATCHED[@]}" -eq 10 ] || { echo "Expected 10 patched files, found ${#PATCHED[@]}" >&2; exit 1; }
: >"$OUTPUT/wheel_vs_source.tsv"
for rel in "${PATCHED[@]}"; do
  wheel_sha="$(sha256sum "$SITE/$rel" | cut -d' ' -f1)"
  commit_sha="$(git -C "$VLLM_DIR" show "HEAD:$rel" | sha256sum | cut -d' ' -f1)"
  printf '%s\t%s\t%s\n' "$rel" "$wheel_sha" "$commit_sha" >>"$OUTPUT/wheel_vs_source.tsv"
  if [ "$wheel_sha" != "$commit_sha" ]; then
    echo "wheel file differs from $VLLM_COMMIT: $rel" >&2
    exit 1
  fi
done
log "wheel matches the pinned commit for all ${#PATCHED[@]} patched files"

# 5. Apply the author overlay to the pinned checkout, then install exactly the
# patched modules (and the new helper module) over the wheel.
git -C "$VLLM_DIR" checkout -q -- .
git -C "$VLLM_DIR" clean -qfd
log "applying overlay"
bash "$X2_DIR/voxtral-realtime/scripts/install_vllm_overlay.sh" "$VLLM_DIR" \
  >"$OUTPUT/overlay_install.log" 2>&1
: >"$OUTPUT/patched_files.tsv"
for rel in "${PATCHED[@]}"; do
  install -Dm644 "$VLLM_DIR/$rel" "$SITE/$rel"
  patched_sha="$(sha256sum "$SITE/$rel" | cut -d' ' -f1)"
  wheel_sha="$(awk -F'\t' -v key="$rel" '$1==key {print $2}' "$OUTPUT/wheel_vs_source.tsv")"
  commit_sha="$(awk -F'\t' -v key="$rel" '$1==key {print $3}' "$OUTPUT/wheel_vs_source.tsv")"
  printf '%s\t%s\t%s\t%s\n' "$rel" "$wheel_sha" "$commit_sha" "$patched_sha" \
    >>"$OUTPUT/patched_files.tsv"
done
UTILS_REL="vllm/model_executor/models/voxtral_mtp_utils.py"
install -Dm644 "$VLLM_DIR/$UTILS_REL" "$SITE/$UTILS_REL"
UTILS_SHA="$(sha256sum "$SITE/$UTILS_REL" | cut -d' ' -f1)"

# 6. Import check: the served model only reports turns if this module loads and
# the realtime protocol exposes turn.delta.
"$PY" - >"$OUTPUT/import_check.json" 2>"$OUTPUT/import_check.log" <<'PY'
import json
import vllm
from vllm.entrypoints.openai.realtime.protocol import TurnDelta
from vllm.model_executor.models.voxtral_mtp_utils import (
    TURN_CLASS_IDS,
    TURN_CLASS_NAMES,
)
print(json.dumps({
    "vllm_version": vllm.__version__,
    "vllm_module": vllm.__file__,
    "turn_delta": TurnDelta.__name__,
    "turn_class_ids": TURN_CLASS_IDS,
    "turn_class_names": TURN_CLASS_NAMES,
}, indent=2))
PY

"$PY" - "$OUTPUT" "$ROOT" "$ENV_PREFIX" "$VLLM_DIR" "$X2_DIR" "$SITE" \
  "$VLLM_TAG" "$VLLM_COMMIT" "$X2_TURN_COMMIT" "$UTILS_REL" "$UTILS_SHA" \
  "$PIP_INDEX" "$CONDA_MIRROR" "$HF_ENDPOINT" "$(capacity)" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, root, prefix, vllm_dir, x2_dir, site, tag, vllm_commit,
 x2_commit, utils_rel, utils_sha, pip_index, conda_mirror, endpoint, free_gib) = sys.argv[1:]
output = Path(output)
patched = {}
for line in (output / "patched_files.tsv").read_text().splitlines():
    rel, wheel_sha, commit_sha, patched_sha = line.split("\t")
    patched[rel] = {
        "wheel_sha256": wheel_sha,
        "pinned_commit_sha256": commit_sha,
        "patched_sha256": patched_sha,
    }
import_check = json.loads((output / "import_check.json").read_text())
installed = {}
for package in ("vllm", "torch", "mistral-common", "huggingface_hub", "websockets", "soundfile"):
    for line in (output / "pip_freeze.txt").read_text().splitlines():
        if line.lower().replace("_", "-").startswith(package.lower() + "=="):
            installed[package] = line.split("==", 1)[1]
            break
lock = {
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "root": root,
    "conda_env": prefix,
    "python": (output / "python_version.txt").read_text().strip(),
    "install_method": "official wheel + pinned overlay patch",
    "pip_index": pip_index,
    "conda_mirror": conda_mirror,
    "hf_endpoint": endpoint,
    "free_disk_gib_after": float(free_gib),
    "vllm": {
        "version": import_check["vllm_version"],
        "tag": tag,
        "commit": vllm_commit,
        "source_checkout": vllm_dir,
        "site_packages": site,
        "patched_files": patched,
        "overlay_helper": {"path": utils_rel, "sha256": utils_sha},
        "wheel_matches_pinned_commit": all(
            item["wheel_sha256"] == item["pinned_commit_sha256"]
            for item in patched.values()
        ),
    },
    "x2_turn_source": {"path": x2_dir, "commit": x2_commit},
    "packages": installed,
    "import_check": import_check,
    "pip_freeze": (output / "pip_freeze.txt").read_text().splitlines(),
}
target = Path(root) / "env" / "x2_turn_vllm_environment.json"
temporary = target.with_name(target.name + ".part")
temporary.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
os.replace(temporary, target)
print(f"wrote {target}")
PY

log "environment ready: $ENV_PREFIX"
log "free disk after install: $(capacity) GiB"
