#!/usr/bin/env bash
# Fallback: build a flash-attn wheel inside the round-one image so the CUDA
# toolkit and PyTorch versions match the runtime exactly, then drop the wheel
# under $XTALK_ROUND1_ROOT/wheels.
#
# NOTE: the round-one image normally consumes a *prebuilt* flash-attn wheel
# (official cu12torch2.8, cp312) staged in the wheelhouse, so no CUDA
# compilation is needed.  This script is only the fallback for when no matching
# prebuilt wheel exists.  Compiling flash-attn is extremely memory hungry (each
# nvcc job peaks at ~8-9 GB), and an unbounded build previously OOM-killed the
# shared debug host, so this script is deliberately conservative:
#   * builds a single CUDA arch (FLASH_ATTN_CUDA_ARCHS, default 80 -> runs on
#     the 8.x family via minor-version binary compatibility, e.g. RTX 4090 /
#     sm_89); flash-attn ignores TORCH_CUDA_ARCH_LIST, so do NOT rely on it,
#   * runs the container with --memory/--memory-swap/--cpus so it can never
#     OOM the host,
#   * keeps MAX_JOBS and NVCC_THREADS low,
#   * sets FLASH_ATTENTION_FORCE_BUILD=TRUE to skip the GitHub prebuilt probe.
#
# Usage:
#   bash scripts/remote/build_round1_flash_attn.sh
# Overrides: IMAGE, FLASH_ATTN_VERSION, FLASH_ATTN_CUDA_ARCHS, MOSS_ENV,
#            MAX_JOBS, NVCC_THREADS, DOCKER_MEMORY, DOCKER_CPUS.
set -euo pipefail

IMAGE="${IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.2}"
XTALK_ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
FLASH_ATTN_VERSION="${FLASH_ATTN_VERSION:-2.8.3.post1}"
FLASH_ATTN_CUDA_ARCHS="${FLASH_ATTN_CUDA_ARCHS:-80}"
MAX_JOBS="${MAX_JOBS:-8}"
NVCC_THREADS="${NVCC_THREADS:-1}"
DOCKER_MEMORY="${DOCKER_MEMORY:-48g}"
DOCKER_CPUS="${DOCKER_CPUS:-8}"
MOSS_ENV="${MOSS_ENV:-xtalk-round1-moss}"
OUT="$XTALK_ROUND1_ROOT/wheels"
mkdir -p "$OUT"

echo "[fa-build] image=$IMAGE version=$FLASH_ATTN_VERSION arch=$FLASH_ATTN_CUDA_ARCHS jobs=$MAX_JOBS threads=$NVCC_THREADS mem=$DOCKER_MEMORY cpus=$DOCKER_CPUS"
docker run --rm \
  --cpus "$DOCKER_CPUS" --memory "$DOCKER_MEMORY" --memory-swap "$DOCKER_MEMORY" \
  -v "$XTALK_ROUND1_ROOT:$XTALK_ROUND1_ROOT" \
  --entrypoint bash "$IMAGE" -lc "
    set -euo pipefail
    export CUDA_HOME=/usr/local/cuda
    export PATH=\$CUDA_HOME/bin:\$PATH
    export PIP_DISABLE_PIP_VERSION_CHECK=1
    source /opt/conda/etc/profile.d/conda.sh
    conda activate $MOSS_ENV
    python -c 'import torch; print(\"torch\", torch.__version__)'
    /usr/local/cuda/bin/nvcc --version | tail -2
    pip install -q psutil setuptools wheel
    rm -rf /tmp/fa_wheel && mkdir -p /tmp/fa_wheel
    MAX_JOBS=$MAX_JOBS NVCC_THREADS=$NVCC_THREADS \
      FLASH_ATTENTION_FORCE_BUILD=TRUE FLASH_ATTN_CUDA_ARCHS=$FLASH_ATTN_CUDA_ARCHS \
      pip wheel flash-attn==$FLASH_ATTN_VERSION --no-build-isolation --no-deps \
      -w /tmp/fa_wheel
    cp /tmp/fa_wheel/flash_attn-*.whl $OUT/
    echo '[fa-build] produced:'; ls -la $OUT/
  "
echo "[fa-build] done"
