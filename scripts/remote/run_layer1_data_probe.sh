#!/usr/bin/env bash
# Validate published-tokenizer data code, then optionally recover source downloads.
set -euo pipefail
ROOT="${LAYER1_DATA_ROOT:?set immutable source checkout}"
TRAIN_ROOT="${LAYER1_TRAIN_ROOT:?set training workspace}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set independent conda prefix}"
OUT="${LAYER1_PROBE_OUTPUT:?set a new diagnostic output directory}"
TOKENIZER="${LAYER1_TOKENIZER:?set published tokenizer directory}"
PY="$ENV_PREFIX/bin/python"
[[ -x "$PY" && -f "$ENV_PREFIX/conda-meta/history" && ! -e "$OUT" ]] || exit 2
mkdir -p "$OUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUT/exit_code.txt"' EXIT
export PYTHONNOUSERSITE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
ulimit -v 7340032
ulimit -c 0
cd "$ROOT"
git rev-parse HEAD > "$OUT/source_commit.txt"
sha256sum scripts/training/*.py scripts/remote/probe_layer1_data.py \
  scripts/remote/run_layer1_data_probe.sh configs/layer1_data.yaml > "$OUT/source.sha256"
"$PY" -m pip freeze > "$OUT/environment.txt"
timeout 120 "$PY" -m unittest discover -s tests -p test_layer1_data_pipeline.py -v > "$OUT/pipeline-tests.txt" 2>&1
timeout 120 "$PY" -m unittest discover -s tests -p test_fetch_layer1_sources.py -v > "$OUT/download-tests.txt" 2>&1
timeout 300 "$PY" scripts/remote/probe_layer1_data.py --config configs/layer1_data.yaml \
  --source-manifest reports/layer1_training/issue001-inventory-20261018/data_source_manifest.json \
  --source-dir "$TRAIN_ROOT/data/ultrachat" --tokenizer "$TOKENIZER" \
  --output "$OUT/probe" --samples 32 --max-length 4096 > "$OUT/probe.log" 2>&1
printf '0\n' > "$OUT/probe_exit_code.txt"
if [[ "${LAYER1_RECOVER_SOURCE:-0}" == 1 ]]; then
  timeout --signal=TERM --kill-after=30 14400 "$PY" -u scripts/training/fetch_layer1_sources.py \
    --manifest reports/layer1_training/issue001-inventory-20261018/data_source_manifest.json \
    --output "$TRAIN_ROOT/data/ultrachat" --endpoint https://hf-mirror.com \
    --attempts 4 --retry-delay 5 > "$OUT/source-recovery.log" 2>&1
fi
