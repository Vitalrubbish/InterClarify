#!/usr/bin/env bash
# Run the current native ASR-control-TTS path with official Layer 1 weights.
set -euo pipefail
ROOT="${FULL_CHAIN_ROOT:?set frozen source root}"
OUTPUT="${FULL_CHAIN_OUTPUT:?set new output directory}"
HOME_ROOT=/hpc_stor03/sjtu_home/xuan.zhang
MODEL_ENV="$HOME_ROOT/miniconda3/envs/interclarify-dev"
CLIENT_ENV="$HOME_ROOT/miniconda3/envs/xtalk-round1-client"
COMPONENT_ROOT="$HOME_ROOT/interclarify-english-integration-20261018-v6"
MODEL_HOME="$HOME_ROOT/interclarify-p0-models/modelscope"
CHECKPOINT="$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28"
BASE="$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a"
ASR="$HOME_ROOT/interclarify-asr-selection/models/nemotron_en"
KOKORO="$HOME_ROOT/interclarify-tts-selection-20261018/models/hf/hub/models--hexgrad--Kokoro-82M/snapshots/f3ff3571791e39611d31c381e3a41a3af07b4987"
WARMUP="$HOME_ROOT/interclarify-asr-selection/dataset/dev/786465049904960526.wav"
[ ! -e "$OUTPUT" ] || exit 2
mkdir -p "$OUTPUT"
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/xtalk/src:$ROOT/scripts/remote" OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
IFS=',' read -r -a GPUS <<< "${CUDA_VISIBLE_DEVICES:-0,1}"
[ "${#GPUS[@]}" -eq 2 ] || { echo 'Exactly two allocated GPUs required' >&2; exit 2; }
PIDS=()
cleanup() {
  local rc=$?
  trap - EXIT
  for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sha256sum -c source.sha256 > "$OUTPUT/source_check.txt"
setsid nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv -l 1 > "$OUTPUT/gpu_samples.csv" &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[0]}" setsid "$MODEL_ENV/bin/python" -u scripts/remote/duplex_model_service.py \
  --checkpoint "$CHECKPOINT" --base-model "$BASE" --port 18806 > "$OUTPUT/model.log" 2>&1 &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[1]}" setsid "$COMPONENT_ROOT/envs/asr/bin/python" -u scripts/remote/nemotron_asr_service.py \
  --model "$ASR" --warmup-audio "$WARMUP" --port 18805 > "$OUTPUT/asr.log" 2>&1 &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[1]}" setsid "$COMPONENT_ROOT/envs/tts/bin/python" -u scripts/remote/kokoro_tts_service.py \
  --snapshot "$KOKORO" --port 18804 > "$OUTPUT/tts.log" 2>&1 &
PIDS+=("$!")
for port in 18806 18805 18804; do
  ready=0
  for attempt in $(seq 1 240); do
    if curl -sf --max-time 2 "http://127.0.0.1:$port/health" > "$OUTPUT/health-$port.json"; then ready=1; break; fi
    sleep 1
  done
  [ "$ready" -eq 1 ] || { echo "Readiness failed: $port" >&2; exit 1; }
done
"$CLIENT_ENV/bin/python" -u scripts/remote/full_chain_smoke.py \
  --manifest "$HOME_ROOT/interclarify-asr-selection/runs/endpoint-b4d12d6/manifest.json" \
  --asr-url http://127.0.0.1:18805 --tts-url http://127.0.0.1:18804 \
  --model-url http://127.0.0.1:18806 --output "$OUTPUT/replay" > "$OUTPUT/client.log" 2>&1
