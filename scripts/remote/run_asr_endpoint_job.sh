#!/usr/bin/env bash
# Observe official DuplexCascade response behavior from genuine ASR trajectories.
set -euo pipefail
ASR_ROOT="${ASR_SELECTION_ROOT:?set ASR_SELECTION_ROOT}"
ASR_SOURCE="${ASR_SELECTION_SOURCE:?set ASR_SELECTION_SOURCE}"
ENDPOINT_RUN="${ASR_ENDPOINT_RUN:?set ASR_ENDPOINT_RUN}"
PROJECT_ROOT="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
MODEL_ENV="${DUPLEX_MODEL_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev}"
CLIENT_ENV="${ASR_ENDPOINT_CLIENT_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-round1-client}"
MODEL_HOME="${DUPLEX_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
FDB_ROOT="${ASR_ENDPOINT_FDB:-/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0}"
mkdir -p "$ENDPOINT_RUN"
exec > >(tee -a "$ENDPOINT_RUN/run.log") 2>&1
sha256sum -c "$ASR_SOURCE.sha256" > "$ENDPOINT_RUN/source_check.txt"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
export PYTHONPATH="$ASR_SOURCE:$PROJECT_ROOT/xtalk/src"
nvidia-smi --query-gpu=name,uuid,driver_version --format=csv > "$ENDPOINT_RUN/gpu.csv"
ASR_TRACES="$ENDPOINT_RUN/asr"
if [ -n "${ASR_ENDPOINT_EXISTING_ASR:-}" ]; then
  cp "$ASR_ENDPOINT_EXISTING_ASR/manifest.json" "$ENDPOINT_RUN/manifest.json"
  ASR_TRACES="$ASR_ENDPOINT_EXISTING_ASR/asr"
else
  "$ASR_ROOT/envs/nemotron_en/bin/python" "$ASR_SOURCE/prepare_asr_endpoint.py" \
    --root "$ASR_ROOT" --fdb "$FDB_ROOT" --output "$ENDPOINT_RUN/manifest.json"
  for config in nemotron_en:160 nemotron_en:560 nemotron_multi:320 nemotron_multi:560 kyutai:500; do
  candidate="${config%:*}"
  chunk="${config#*:}"
  out="$ENDPOINT_RUN/asr/$candidate-$chunk"
  mkdir -p "$out"
  timeout 900 "$ASR_ROOT/envs/$candidate/bin/python" -u "$ASR_SOURCE/benchmark_asr_selection.py" \
    --root "$ASR_ROOT" --manifest "$ENDPOINT_RUN/manifest.json" \
    --candidate "$candidate" --chunk-ms "$chunk" --limit 5 --output "$out" \
    > "$out/process.log" 2>&1
  done
fi
for config in nemotron_en-160 nemotron_en-560 nemotron_multi-320 nemotron_multi-560 kyutai-500; do
  test -f "$ASR_TRACES/$config/report.json"
done
MODEL_PORT="${ASR_ENDPOINT_MODEL_PORT:-8016}"
"$MODEL_ENV/bin/python" -u "$ASR_SOURCE/duplex_model_service.py" \
  --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
  --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
  --port "$MODEL_PORT" > "$ENDPOINT_RUN/model.log" 2>&1 &
MODEL_PID=$!
trap 'kill "$MODEL_PID" 2>/dev/null || true; wait "$MODEL_PID" 2>/dev/null || true' EXIT
ready=0
for ((attempt=0; attempt<180; attempt++)); do
  kill -0 "$MODEL_PID" || { echo "Model service exited"; exit 1; }
  if curl -fsS --max-time 2 "http://127.0.0.1:$MODEL_PORT/health" > "$ENDPOINT_RUN/model_health.json" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
[ "$ready" -eq 1 ] || { echo "Model service not ready"; exit 1; }
"$CLIENT_ENV/bin/python" -u "$ASR_SOURCE/replay_asr_endpoint.py" \
  --model-url "http://127.0.0.1:$MODEL_PORT" \
  --manifest "$ENDPOINT_RUN/manifest.json" --asr-run "$ASR_TRACES" \
  --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
  --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
  --output "$ENDPOINT_RUN/control"
