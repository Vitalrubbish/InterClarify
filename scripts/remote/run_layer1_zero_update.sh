#!/usr/bin/env bash
# Compare independently restored official and training models on one allocated GPU.
set -euo pipefail
ROOT="${LAYER1_ZERO_ROOT:?set immutable source checkout}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set independent training conda prefix}"
OUTPUT="${LAYER1_ZERO_OUTPUT:?set a new output directory}"
MODEL_HOME="${LAYER1_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
OFFICIAL="${LAYER1_OFFICIAL_SOURCE:-/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade}"
[[ ! -e "$OUTPUT" ]] || exit 2
mkdir -p "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ -x "$ENV_PREFIX/bin/python" && -f "$ENV_PREFIX/conda-meta/history" ]] || exit 2
if [[ -z "${JobID:-}" || ( -z "${CUDA_VISIBLE_DEVICES:-}" && -z "${NVIDIA_VISIBLE_DEVICES:-}" ) ]]; then
  echo 'A scheduled job and an allocated GPU are required' > "$OUTPUT/gpu-preflight.log"
  exit 2
fi
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
ulimit -v 29360128
ulimit -c 0
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
sha256sum scripts/training/layer1_model.py scripts/training/check_layer1_zero_update.py \
  scripts/remote/duplex_model_service.py scripts/remote/run_layer1_zero_update.sh \
  configs/layer1_zero_update.yaml > "$OUTPUT/source.sha256"
timeout 60 "$ENV_PREFIX/bin/python" - "$OUTPUT/gpu_preflight.json" > "$OUTPUT/gpu-preflight.log" 2>&1 <<'PY'
import json
import os
from pathlib import Path
import sys

import torch

info = {key: os.environ.get(key) for key in ('JobID', 'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES')}
info.update(cuda_available=torch.cuda.is_available(), device_count=torch.cuda.device_count())
if info['cuda_available'] and info['device_count'] == 1:
    device = torch.cuda.get_device_properties(0)
    info.update(name=device.name, total_memory=device.total_memory, bf16_supported=torch.cuda.is_bf16_supported())
Path(sys.argv[1]).write_text(json.dumps(info, indent=2) + '\n')
if not (info['cuda_available'] and info['device_count'] == 1
        and '4090' in info['name'] and 22 * 1024**3 <= info['total_memory'] <= 25 * 1024**3
        and info['bf16_supported']):
    raise RuntimeError('Expected exactly one allocated 24 GiB RTX 4090 with BF16 support')
PY
"$ENV_PREFIX/bin/python" -c 'from importlib.metadata import distributions; print("\n".join(sorted((d.metadata.get("Name") or "unknown") + "==" + d.version for d in distributions())))' > "$OUTPUT/environment.txt"
nvidia-smi --query-gpu=name,uuid,memory.total --format=csv > "$OUTPUT/gpu.csv"
timeout 120 "$ENV_PREFIX/bin/python" -m unittest discover -s tests -p test_layer1_loading.py -v > "$OUTPUT/loading-tests.txt" 2>&1
timeout 120 "$ENV_PREFIX/bin/python" -m unittest discover -s tests -p test_duplex_model_service.py -v > "$OUTPUT/service-tests.txt" 2>&1
timeout --signal=TERM --kill-after=30 1500 "$ENV_PREFIX/bin/python" -u \
  scripts/training/check_layer1_zero_update.py --root "$ROOT" \
  --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
  --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
  --official-source "$OFFICIAL" --device cuda --output "$OUTPUT/comparison" \
  > "$OUTPUT/zero-update.log" 2>&1
du -sk "$OUTPUT" > "$OUTPUT/disk_usage.txt"
