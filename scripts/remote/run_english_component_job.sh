#!/usr/bin/env bash
# Run one explicit backend on a scheduler-allocated GPU with isolated evidence.
set -euo pipefail
ROOT="${ENGLISH_COMPONENT_ROOT:?set frozen experiment root}"
BACKEND="${ENGLISH_COMPONENT_BACKEND:?set asr or tts}"
OUTPUT="${ENGLISH_COMPONENT_OUTPUT:?set a new output directory}"
CLIENT_ENV="${ENGLISH_CLIENT_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-round1-client}"
WARMUP="${ENGLISH_WARMUP_AUDIO:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/dataset/dev/786465049904960526.wav}"
ASR_MODEL="${ENGLISH_ASR_MODEL:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/models/nemotron_en}"
KOKORO="${ENGLISH_KOKORO_SNAPSHOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-tts-selection-20261018/models/hf/hub/models--hexgrad--Kokoro-82M/snapshots/f3ff3571791e39611d31c381e3a41a3af07b4987}"
case "$BACKEND" in asr|tts) ;; *) exit 2 ;; esac
[ ! -e "$OUTPUT" ] || { echo "Output already exists" >&2; exit 2; }
mkdir -p "$OUTPUT"
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export PYTHONPATH="$ROOT/xtalk/src:$ROOT/scripts/remote"
SERVER=''
MONITOR=''
cleanup() {
  local rc=$?
  trap - EXIT
  if [ -n "$SERVER" ]; then
    if [ -r "/proc/$SERVER/status" ]; then
      cat "/proc/$SERVER/status" > "$OUTPUT/service_process_status.txt"
    fi
    kill -TERM -- "-$SERVER" 2>/dev/null || true
    wait "$SERVER" 2>/dev/null || true
  fi
  if [ -n "$MONITOR" ]; then kill "$MONITOR" 2>/dev/null || true; fi
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sha256sum -c source.sha256 > "$OUTPUT/source_check.txt"
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$OUTPUT/gpu.csv"
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 1 > "$OUTPUT/gpu_samples.csv" &
MONITOR=$!
PORT=18805
if [ "$BACKEND" = asr ]; then
  setsid "$ROOT/envs/asr/bin/python" -u scripts/remote/nemotron_asr_service.py \
    --model "$ASR_MODEL" --warmup-audio "$WARMUP" --port "$PORT" > "$OUTPUT/service.log" 2>&1 &
else
  PORT=18804
  setsid "$ROOT/envs/tts/bin/python" -u scripts/remote/kokoro_tts_service.py \
    --snapshot "$KOKORO" --port "$PORT" > "$OUTPUT/service.log" 2>&1 &
fi
SERVER=$!
"$CLIENT_ENV/bin/python" - "$PORT" "$SERVER" "$OUTPUT/health.json" <<'PY'
import json,os,sys,time,urllib.request
for _ in range(180):
    os.kill(int(sys.argv[2]),0)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{sys.argv[1]}/health',timeout=2) as response:
            value=json.load(response)
        with open(sys.argv[3],'w') as output:
            json.dump(value,output,indent=2)
        break
    except OSError:
        time.sleep(1)
else:
    raise TimeoutError('Component did not complete model loading and real warmup')
PY
"$CLIENT_ENV/bin/python" -u scripts/remote/verify_english_components.py \
  --backend "$BACKEND" --url "http://127.0.0.1:$PORT" --audio "$WARMUP" \
  --output "$OUTPUT/verification" > "$OUTPUT/client.log" 2>&1
