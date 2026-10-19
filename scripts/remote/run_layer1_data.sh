#!/usr/bin/env bash
# Build and audit Layer 1 text data inside one scheduled CPU allocation.
set -euo pipefail
ROOT="${LAYER1_DATA_ROOT:?set immutable source checkout}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set existing conda prefix}"
SOURCE="${LAYER1_SOURCE_DIR:?set verified shard directory}"
SOURCE_MANIFEST="${LAYER1_SOURCE_MANIFEST:?set pinned source manifest}"
TOKENIZER="${LAYER1_TOKENIZER:?set published tokenizer directory}"
EXCLUSIONS="${LAYER1_EXCLUSIONS:?set explicit exclusion manifest}"
OUTPUT="${LAYER1_DATA_OUTPUT:?set unique run output}"
MAX_LENGTH="${LAYER1_DATA_MAX_LENGTH:?set audit length pending issue005 freeze}"
CONFIG="${LAYER1_DATA_CONFIG:-$ROOT/configs/layer1_data.yaml}"
[[ -x "$ENV_PREFIX/bin/python" && -f "$ENV_PREFIX/conda-meta/history" ]] || exit 2
[[ ! -e "$OUTPUT" ]] || { echo 'Output exists; use the Python --resume entry explicitly' >&2; exit 2; }
mkdir -p "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
ulimit -v 29360128
ulimit -c 0
"$ENV_PREFIX/bin/python" -c 'import tokenizers, yaml, sqlite3'
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
"$ENV_PREFIX/bin/python" -c 'from importlib.metadata import distributions; print("\n".join(sorted((d.metadata.get("Name") or "unknown") + "==" + d.version for d in distributions())))' > "$OUTPUT/environment.txt"
timeout --signal=TERM --kill-after=30 14400 "$ENV_PREFIX/bin/python" -u \
  scripts/training/build_layer1_dataset.py --config "$CONFIG" \
  --source-manifest "$SOURCE_MANIFEST" --source-dir "$SOURCE" \
  --download-manifest "$SOURCE/download_manifest.json" --tokenizer "$TOKENIZER" \
  --exclusions "$EXCLUSIONS" --max-length "$MAX_LENGTH" --output "$OUTPUT/dataset" \
  > "$OUTPUT/build.log" 2>&1
timeout --signal=TERM --kill-after=30 3600 "$ENV_PREFIX/bin/python" -u \
  scripts/training/audit_layer1_dataset.py --dataset "$OUTPUT/dataset" \
  --tokenizer "$TOKENIZER" --output "$OUTPUT/audit.json" > "$OUTPUT/audit.log" 2>&1
timeout --signal=TERM --kill-after=30 1800 "$ENV_PREFIX/bin/python" -u \
  scripts/training/prepare_layer1_review.py --dataset "$OUTPUT/dataset" --audit "$OUTPUT/audit.json" \
  --tokenizer "$TOKENIZER" --output "$OUTPUT/review" > "$OUTPUT/review.log" 2>&1
