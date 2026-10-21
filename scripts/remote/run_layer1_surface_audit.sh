#!/usr/bin/env bash
# Audit the frozen dataset and historical ASR traces without model execution.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE=/hpc_stor03/sjtu_home/xuan.zhang
TRAINING="$BASE/interclarify-layer1-training-20261019"
PYTHON="$TRAINING/envs/training/bin/python"
OUTPUT="${ISSUE073_OUTPUT:?set independent run directory}"
[[ "$(git -C "$ROOT" rev-parse HEAD)" = "${ISSUE073_SOURCE_COMMIT:?set frozen commit}" ]] || exit 2
[[ -f "$TRAINING/envs/training/conda-meta/history" && ! -e "$OUTPUT" ]] || exit 2
mkdir -p "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ulimit -v 4194304
ulimit -f 262144
ulimit -c 0
taskset -pc "$(awk '/Cpus_allowed_list/ {split($2, a, /[-,]/); print a[1]}' /proc/self/status)" "$$"
renice 10 -p "$$"
git -C "$ROOT" rev-parse HEAD > "$OUTPUT/source_commit.txt"
"$PYTHON" -c 'import sys; print(sys.version); print(sys.prefix)' > "$OUTPUT/environment.txt"
timeout --signal=TERM --kill-after=30 1800 "$PYTHON" -u "$ROOT/scripts/training/audit_layer1_surface.py" \
  --dataset "$TRAINING/data/runs/issue040-delayed-start-data/dataset" \
  --audit "$TRAINING/data/runs/issue040-delayed-start-data/audit.json" \
  --protocol "$ROOT/configs/layer1_delayed_protocol.yaml" \
  --index "$ROOT/reports/layer1_training/issue040-delayed-training-20261020/full_train_index.json" \
  --tokenizer "$BASE/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28/tokenizer" \
  --asr-root "$BASE/interclarify-asr-selection/runs/full100-parallel-13a846d" \
  --output "$OUTPUT/audit" > "$OUTPUT/audit.log" 2>&1
