#!/usr/bin/env bash
# Diagnose frozen cache divergence in a bounded scheduled allocation.
set -euo pipefail
DIAG_ROOT="${KV_DIAG_ROOT:?set new diagnostic root}"
HOME_ROOT=/hpc_stor03/sjtu_home/xuan.zhang
SOURCE="$HOME_ROOT/interclarify-latency-20261021-r2/source"
MODEL_ENV="$HOME_ROOT/interclarify-layer1-training-20261019/envs/training"
MODEL_HOME="$HOME_ROOT/interclarify-p0-models/modelscope"
TRAIN_RUN="$HOME_ROOT/interclarify-layer1-training-20261019/data/runs/issue040-delayed-start-r1"
OUTPUT="$DIAG_ROOT/output"
[[ -n "${JobID:-}" && -f "$MODEL_ENV/conda-meta/history" ]] || exit 2
[[ ! -e "$OUTPUT" ]] || exit 2
mkdir -p "$DIAG_ROOT"
trap 'rc=$?; printf "%s\n" "$rc" > "$DIAG_ROOT/exit_code.txt"' EXIT
ulimit -c 0
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export PYTHONPATH="$SOURCE/scripts/remote:$SOURCE/scripts/training"
cd "$SOURCE"
sha256sum -c source.sha256 > "$DIAG_ROOT/source_verification.txt"
"$MODEL_ENV/bin/python" - "$DIAG_ROOT" <<'PY'
import shutil,sys
from pathlib import Path
import torch
p=Path(sys.argv[1])
assert shutil.disk_usage(p).free > 15*1024**3
assert torch.cuda.device_count()==2
assert all('4090' in torch.cuda.get_device_name(i) for i in range(2))
PY
"$MODEL_ENV/bin/python" -u "$DIAG_ROOT/diagnose_kv_cache.py" \
 --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
 --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
 --adaptation "$TRAIN_RUN/training/checkpoint.pt" \
 --trace "$HOME_ROOT/interclarify-latency-20261021-r2/data/r2/model_trace.jsonl" \
 --output "$OUTPUT" > "$DIAG_ROOT/diagnostic.log" 2>&1
"$MODEL_ENV/bin/python" - "$DIAG_ROOT" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
assert sum(q.stat().st_size for q in p.rglob('*') if q.is_file()) < 2*1024**3
PY
