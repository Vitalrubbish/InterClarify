#!/usr/bin/env bash
# Train the frozen second-round T2 condition without pretraining short runs.
set -euo pipefail
ROOT="${LAYER1_TRAIN_ROOT:?set frozen source checkout}"
TRAINING_ROOT="${LAYER1_TRAINING_ROOT:?set experiment root}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set independent training conda prefix}"
OUTPUT="${LAYER1_TRAIN_OUTPUT:?set new round-two T2 output}"
ARM=T2
MODEL_HOME="${LAYER1_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
OFFICIAL="${LAYER1_OFFICIAL_SOURCE:-/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade}"
[[ -x "$ENV_PREFIX/bin/python" && -f "$ENV_PREFIX/conda-meta/history" ]] || exit 2
mkdir -p "$(dirname "$OUTPUT")"
mkdir "$OUTPUT" || exit 2
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 CUBLAS_WORKSPACE_CONFIG=:4096:8
ulimit -c 0
"$ENV_PREFIX/bin/python" - "$ROOT" <<'PY_CHECK'
from pathlib import Path
import os
import sys
import yaml
sys.path.insert(0, 'scripts/training')
from prepare_layer1_adaptation import validate_alignment_config
from train_layer1 import check_disk
root = Path(sys.argv[1])
config = yaml.safe_load((root / 'configs/layer1_alignment_training.yaml').read_text())
protocol = yaml.safe_load((root / 'configs/layer1_alignment_protocol.yaml').read_text())
validate_alignment_config(config, protocol, root, 'T2', 1000, 2048, 1214)
check_disk(Path(os.environ['LAYER1_TRAIN_OUTPUT']), {'max_output_gib': 6, 'min_free_gib': 5})
PY_CHECK
[[ -n "${JobID:-}" && ( -n "${CUDA_VISIBLE_DEVICES:-}" || -n "${NVIDIA_VISIBLE_DEVICES:-}" ) ]] || exit 2
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
sha256sum scripts/training/train_layer1.py scripts/training/prepare_layer1_adaptation.py \
  scripts/training/layer1_model.py scripts/training/layer1_data.py scripts/training/number_surface.py \
  scripts/training/layer1_loss.py scripts/training/layer1_candidate.py \
  scripts/training/run_layer1_alignment.py scripts/remote/run_layer1_t2_round2.sh configs/layer1_alignment_training.yaml \
  configs/layer1_alignment_protocol.yaml > "$OUTPUT/source.sha256"
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
assert info['available'] and info['count'] == 1 and '4090' in info['name']
assert 22 * 1024**3 <= info['total_memory'] <= 25 * 1024**3 and info['bf16']
PY
"$ENV_PREFIX/bin/python" -c 'from importlib.metadata import distributions; print("\n".join(sorted((d.metadata.get("Name") or "unknown") + "==" + d.version for d in distributions())))' > "$OUTPUT/environment.txt"
timeout --signal=TERM --kill-after=30 27900 "$ENV_PREFIX/bin/python" -u \
  scripts/training/train_layer1.py train --arm "$ARM" \
  --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
  --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
  --official-source "$OFFICIAL" \
  --inventory "$ROOT/reports/layer1_training/issue001-inventory-20261018/inventory_summary.json" \
  --dataset "$TRAINING_ROOT/data/runs/issue004-build-r5/dataset" \
  --audit "$TRAINING_ROOT/data/runs/issue004-build-r5/audit.json" \
  --config "$ROOT/configs/layer1_alignment_training.yaml" \
  --protocol "$ROOT/configs/layer1_alignment_protocol.yaml" \
  --dialogues 1000 --length 2048 --steps 1214 --output "$OUTPUT/training" \
  > "$OUTPUT/training.log" 2>&1
timeout --signal=TERM --kill-after=30 900 "$ENV_PREFIX/bin/python" -u \
  scripts/training/run_layer1_alignment.py verify --formal \
  --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
  --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
  --candidate "$OUTPUT/training/checkpoint.pt" --output "$OUTPUT/candidate_reload.json" \
  > "$OUTPUT/candidate_reload.log" 2>&1
"$ENV_PREFIX/bin/python" - "$OUTPUT" <<'PY_CHECK'
import sys
sys.path.insert(0, 'scripts/training')
from train_layer1 import check_disk
check_disk(sys.argv[1], {'max_output_gib': 6, 'min_free_gib': 5})
PY_CHECK
du -sk "$OUTPUT" > "$OUTPUT/disk_usage.txt"
