#!/usr/bin/env bash
# Compare independently restored official and training models on one allocated GPU.
set -euo pipefail
ROOT="${LAYER1_ZERO_ROOT:?set immutable source checkout}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set independent training conda prefix}"
OUTPUT="${LAYER1_ZERO_OUTPUT:?set a new output directory}"
MODEL_HOME="${LAYER1_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
OFFICIAL="${LAYER1_OFFICIAL_SOURCE:-/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade}"
[[ -x "$ENV_PREFIX/bin/python" && -f "$ENV_PREFIX/conda-meta/history" && ! -e "$OUTPUT" ]] || exit 2
[[ -n "${CUDA_VISIBLE_DEVICES:-}" ]] || { echo 'An allocated GPU is required' >&2; exit 2; }
mkdir -p "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
ulimit -v 29360128
ulimit -c 0
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
sha256sum scripts/training/layer1_model.py scripts/training/check_layer1_zero_update.py \
  scripts/remote/duplex_model_service.py configs/layer1_zero_update.yaml > "$OUTPUT/source.sha256"
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
