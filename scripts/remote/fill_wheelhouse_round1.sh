#!/usr/bin/env bash
# Fill the round-one wheelhouse cache with any packages missing for the image
# build.  The wheelhouse is used during the image build only as a local
# `--find-links` cache (remaining deps come from pypi.org), so this script is
# optional; it is useful when a build host wants to pre-stage the big wheels
# (torch cu128, vllm, transformers) before a slower/offline build.
#
# Usage:
#   bash scripts/remote/fill_wheelhouse_round1.sh
#
# Overrides:
#   XTALK_ROUND1_ROOT, ROUND1_PIP_INDEX, ROUND1_TORCH_INDEX, ROUND1_FILL_PYTHON
set -euo pipefail

ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
WHEELS="$ROUND1_ROOT/wheels"
INDEX="${ROUND1_PIP_INDEX:-https://pypi.org/simple/}"
TORCH_INDEX="${ROUND1_TORCH_INDEX:-https://download.pytorch.org/whl/cu128}"
PY="${ROUND1_FILL_PYTHON:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-round1-tools/bin/python}"

if [ ! -x "$PY" ]; then
  echo "[fill] missing python: $PY" >&2
  exit 2
fi
mkdir -p "$WHEELS" "$ROUND1_ROOT/wheels-staging"
STAGE="$ROUND1_ROOT/wheels-staging"

download() {  # download <stage-name> <requirements...>
  local name="$1"; shift
  local dest="$STAGE/$name"
  mkdir -p "$dest"
  echo "[fill] resolving $name"
  "$PY" -m pip download --dest "$dest" \
    --index-url "$INDEX" --extra-index-url "$TORCH_INDEX" "$@" \
    || { echo "[fill] WARNING: $name download incomplete" >&2; return 1; }
}

# Each environment resolves independently so conflicting transformers pins
# (Qwen 4.57.6 vs MOSS 5.0.0) never share a resolution.
download tools PyYAML==6.0.3 huggingface_hub &
download vllm vllm==0.14.0 &
download asr "transformers==4.57.6" "nagisa==0.2.11" "soynlp==0.0.493" \
  "accelerate==1.12.0" qwen-omni-utils librosa soundfile sox gradio flask pytz &
download moss "torch==2.9.1+cu128" "torchaudio==2.9.1+cu128" "transformers==5.0.0" \
  fastapi uvicorn requests soxr websockets &
download client "$ROUND1_ROOT/xtalk[example,dev]" PyYAML==6.0.3 aiohttp soundfile soxr &
wait || true

# Merge every staged wheel into the wheelhouse (identical names overwrite).
find "$STAGE" -name '*.whl' -exec cp -f {} "$WHEELS/" \;
echo "[fill] wheelhouse now holds $(ls "$WHEELS" | wc -l) wheels"
