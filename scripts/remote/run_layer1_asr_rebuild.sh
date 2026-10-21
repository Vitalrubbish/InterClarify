#!/usr/bin/env bash
# Rebuild the original frozen split and audit the delayed-punctuation ASR view.
set -euo pipefail
ROOT="${LAYER1_ASR_ROOT:?set frozen checkout}"
OUTPUT="${LAYER1_ASR_DATA_OUTPUT:?set independent output}"
BASE=/hpc_stor03/sjtu_home/xuan.zhang
TRAINING="$BASE/interclarify-layer1-training-20261019"
PYTHON="$TRAINING/envs/training/bin/python"
[[ -f "$TRAINING/envs/training/conda-meta/history" && ! -e "$OUTPUT" ]] || exit 2
cd "$ROOT"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 PYTHONNOUSERSITE=1 PYTHONOPTIMIZE=0
ulimit -v 4194304
ulimit -f 2097152
ulimit -c 0
taskset -pc "$(awk '/Cpus_allowed_list/ {split($2,a,/[-,]/); print a[1]}' /proc/self/status)" "$$"
renice 10 -p "$$"
trap 'rc=$?; if [[ -d "$OUTPUT" ]]; then printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"; fi' EXIT
for pattern in test_asr_surface.py test_layer1_data_pipeline.py; do
  timeout 120 "$PYTHON" -m unittest discover -s tests -p "$pattern"
done
timeout --signal=TERM --kill-after=30 1800 "$PYTHON" -u scripts/training/rebuild_layer1_asr.py \
  --baseline "$TRAINING/data/runs/issue040-delayed-start-data/dataset" \
  --tokenizer "$BASE/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28/tokenizer" \
  --config "$ROOT/configs/layer1_asr_data.yaml" \
  --review-source "$TRAINING/data/runs/issue073-surface-audit-20261021-r2/audit/review_cards.json" \
  --output "$OUTPUT"
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
