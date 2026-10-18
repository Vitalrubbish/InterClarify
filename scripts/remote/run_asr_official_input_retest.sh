#!/usr/bin/env bash
# Replay one frozen formatting arm on one scheduler-allocated GPU.
set -euo pipefail
ROOT="${ASR_ALIGNMENT_ROOT:?set isolated frozen experiment root}"
ARM="${ASR_ALIGNMENT_ARM:?set legacy or official}"
OUTPUT="${ASR_ALIGNMENT_OUTPUT:-$ROOT/runs/$ARM}"
ASR_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection
MODEL_ENV=/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev
CLIENT_ENV=/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-round1-client
MODEL_HOME=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope
CHECKPOINT="$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28"
BASE="$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a"
TRACES="$ASR_ROOT/runs/endpoint-b4d12d6"
[ ! -e "$OUTPUT" ] || { echo "Output exists: $OUTPUT" >&2; exit 2; }
case "$ARM" in legacy|official) ;; *) exit 2 ;; esac
mkdir -p "$OUTPUT"
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export PYTHONPATH="$ROOT/scripts/remote:$ROOT/source/xtalk/src"
SERVICE="$ROOT/scripts/remote/duplex_model_service.py"
if [ "$ARM" = legacy ]; then SERVICE="$ROOT/source/legacy_service.py"; fi
PORT=18116
SERVER=''
cleanup() {
  local rc=$?
  trap - EXIT
  if [ -n "$SERVER" ]; then
    kill -TERM -- "-$SERVER" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$SERVER" 2>/dev/null || true
    wait "$SERVER" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sha256sum -c source.sha256 > "$OUTPUT/source_check.txt"
nvidia-smi --query-gpu=name,uuid,driver_version --format=csv > "$OUTPUT/gpu.csv"
"$CLIENT_ENV/bin/python" -m unittest discover -s tests -p test_duplex_model_service.py -v > "$OUTPUT/tests.txt" 2>&1
setsid "$MODEL_ENV/bin/python" -u "$SERVICE" --checkpoint "$CHECKPOINT" --base-model "$BASE" --port "$PORT" > "$OUTPUT/model.log" 2>&1 &
SERVER=$!
"$CLIENT_ENV/bin/python" - "$PORT" "$SERVER" "$OUTPUT/health.json" <<'PY'
import json,os,sys,time,urllib.request
for _ in range(300):
    os.kill(int(sys.argv[2]),0)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{sys.argv[1]}/health',timeout=2) as response:
            value=json.load(response)
        open(sys.argv[3],'w').write(json.dumps(value,indent=2))
        break
    except OSError:
        time.sleep(1)
else:
    raise TimeoutError('Model did not become ready')
PY
EXTRA=()
if [ -n "${ASR_ALIGNMENT_CONFIG:-}" ]; then EXTRA+=(--configs "$ASR_ALIGNMENT_CONFIG"); fi
"$CLIENT_ENV/bin/python" -u scripts/remote/retest_asr_official_input.py "${EXTRA[@]}" \
  --arm "$ARM" --model-url "http://127.0.0.1:$PORT" \
  --manifest "$TRACES/manifest.json" --asr-run "$TRACES/asr" \
  --checkpoint "$CHECKPOINT" --base-model "$BASE" --output "$OUTPUT/control" > "$OUTPUT/client.log" 2>&1
