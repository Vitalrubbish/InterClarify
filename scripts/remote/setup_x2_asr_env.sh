#!/usr/bin/env bash
# Prepare the isolated X2 Transformers backend on the remote server.
set -euo pipefail
X2_ROOT="${INTERCLARIFY_X2_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2}"
X2_SOURCE="$X2_ROOT/source-code"
X2_PREFIX="${X2_CONDA_PREFIX:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-x2-asr}"
X2_CONDA="${X2_CONDA:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/bin/conda}"
X2_COMMIT=0aca80597bb1399c0be4002de5bc62c0a779c542
X2_REVISION=4c8df16b8d7f8b50c95590c4d7907436ebe4aa08
mkdir -p "$X2_ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_DISABLE_XET=1
export HF_ENDPOINT="${X2_HF_ENDPOINT:-https://hf-mirror.com}"
if [ ! -d "$X2_SOURCE/.git" ]; then
  git clone --filter=blob:none --no-checkout --depth 1 \
    git@github.com:X-Square-Robot/X2Streaming-ASR.git "$X2_SOURCE"
fi
git -C "$X2_SOURCE" sparse-checkout set models src demo data_pipeline configs tools
git -C "$X2_SOURCE" checkout --detach "$X2_COMMIT"
# A fresh python base is smaller and more reproducible than cloning a shared
# runtime env: the official requirements pin torch/transformers and pull their
# own CUDA wheels, so a torch-capable seed only adds unrelated packages.
if [ ! -f "$X2_PREFIX/conda-meta/history" ]; then
  "$X2_CONDA" create -y -p "$X2_PREFIX" python=3.12 pip
fi
"$X2_CONDA" run --no-capture-output -p "$X2_PREFIX" python -m pip install \
  -r "$X2_SOURCE/requirements.txt" 'fastapi>=0.115.0' 'uvicorn>=0.34.0'
"$X2_CONDA" run --no-capture-output -p "$X2_PREFIX" python -m pip freeze > "$X2_ROOT/requirements.lock.txt"
"$X2_CONDA" run --no-capture-output -p "$X2_PREFIX" python -c \
  'from huggingface_hub import snapshot_download; import sys; snapshot_download("x-square-robot/X2Streaming-ASR-4B-1009", revision=sys.argv[1], local_dir=sys.argv[2], max_workers=4)' \
  "$X2_REVISION" "$X2_ROOT/model"
"$X2_CONDA" run --no-capture-output -p "$X2_PREFIX" python -c \
  'from transformers import VoxtralRealtimeForConditionalGeneration; import torch,fastapi; print("X2 dependencies ready",torch.__version__)'
printf 'source=%s\nmodel=%s\nenv=%s\n' "$X2_COMMIT" "$X2_REVISION" "$X2_PREFIX" > "$X2_ROOT/ready.txt"
