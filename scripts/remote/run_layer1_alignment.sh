#!/usr/bin/env bash
# Validate weighted adaptation and clean restart in one allocated GPU job.
set -euo pipefail
ROOT="${LAYER1_TRAIN_ROOT:?set frozen source checkout}"
TRAINING_ROOT="${LAYER1_TRAINING_ROOT:?set experiment root}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set independent conda prefix}"
OUTPUT="${LAYER1_TRAIN_OUTPUT:?set new output directory}"
MODEL_HOME="${LAYER1_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
OFFICIAL="${LAYER1_OFFICIAL_SOURCE:-/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade}"
[[ -x "$ENV_PREFIX/bin/python" && -f "$ENV_PREFIX/conda-meta/history" ]] || exit 2
[[ -n "${JobID:-}" && ( -n "${CUDA_VISIBLE_DEVICES:-}" || -n "${NVIDIA_VISIBLE_DEVICES:-}" ) ]] || exit 2
mkdir -p "$(dirname "$OUTPUT")"
mkdir "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 CUBLAS_WORKSPACE_CONFIG=:4096:8
ulimit -c 0
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
sha256sum scripts/training/{train_layer1,layer1_loss,layer1_model,layer1_candidate,layer1_data,number_surface,prepare_layer1_adaptation,run_layer1_alignment}.py \
  scripts/remote/run_layer1_alignment.sh configs/layer1_alignment_{training,protocol}.yaml > "$OUTPUT/source.sha256"
"$ENV_PREFIX/bin/python" - "$OUTPUT/gpu_preflight.json" <<'PY'
import json
import os
from pathlib import Path
import sys
import torch
info = {key: os.environ.get(key) for key in ('JobID', 'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES')}
info.update(available=torch.cuda.is_available(), count=torch.cuda.device_count())
if info['available'] and info['count'] == 1:
    device = torch.cuda.get_device_properties(0)
    info.update(name=device.name, total_memory=device.total_memory, bf16=torch.cuda.is_bf16_supported())
Path(sys.argv[1]).write_text(json.dumps(info, indent=2) + '\n')
assert info['available'] and info['count'] == 1 and '4090' in info['name'] and info['bf16']
assert 22 * 1024**3 <= info['total_memory'] <= 25 * 1024**3
PY
"$ENV_PREFIX/bin/python" -c 'from importlib.metadata import distributions; print("\n".join(sorted((d.metadata.get("Name") or "unknown") + "==" + d.version for d in distributions())))' > "$OUTPUT/environment.txt"
timeout --signal=TERM --kill-after=30 3600 "$ENV_PREFIX/bin/python" -u \
  scripts/training/run_layer1_alignment.py run --root "$ROOT" --output "$OUTPUT/run" \
  --training-root "$TRAINING_ROOT" --model-home "$MODEL_HOME" --official-source "$OFFICIAL" \
  > "$OUTPUT/orchestration.log" 2>&1
du -sk "$OUTPUT" > "$OUTPUT/disk_usage.txt"
