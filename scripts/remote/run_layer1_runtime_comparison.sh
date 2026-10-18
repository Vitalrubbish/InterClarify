#!/usr/bin/env bash
# Compare the pinned official control loop against the existing X-Talk runtime.
set -euo pipefail
ROOT="${LAYER1_COMPARISON_ROOT:?set immutable source root}"
OUTPUT="${LAYER1_COMPARISON_OUTPUT:?set new output directory}"
MODEL_ENV="${LAYER1_MODEL_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev}"
CLIENT_ENV="${LAYER1_CLIENT_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-round1-client}"
MODEL_HOME=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope
CHECKPOINT="$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28"
BASE="$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a"
WORD_MANIFEST="${LAYER1_WORD_MANIFEST:?set verified native Word manifest}"
[ -f "$WORD_MANIFEST" ] || exit 2
[ ! -e "$OUTPUT" ] || exit 2
mkdir -p "$OUTPUT"
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export PYTHONPATH="$ROOT/xtalk/src:$ROOT/scripts/remote"
SERVER=''
cleanup() {
  local rc=$?
  trap - EXIT
  if [ -n "$SERVER" ]; then
    kill -TERM -- "-$SERVER" 2>/dev/null || true
    wait "$SERVER" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sha256sum -c source.sha256 > "$OUTPUT/source_check.txt"
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$OUTPUT/gpu.csv"
setsid "$MODEL_ENV/bin/python" -u scripts/remote/duplex_model_service.py \
  --checkpoint "$CHECKPOINT" --base-model "$BASE" --port 18806 > "$OUTPUT/model.log" 2>&1 &
SERVER=$!
"$CLIENT_ENV/bin/python" - "$SERVER" "$OUTPUT/health.json" <<'PY'
import json,os,sys,time,urllib.request
for _ in range(300):
    os.kill(int(sys.argv[1]),0)
    try:
        with urllib.request.urlopen('http://127.0.0.1:18806/health',timeout=2) as response:
            value=json.load(response)
        with open(sys.argv[2],'w') as output:json.dump(value,output,indent=2)
        break
    except OSError:time.sleep(1)
else:raise TimeoutError('Control model did not become ready')
PY
EXTRA=()
if [ -n "${LAYER1_COMPARISON_CASE:-}" ]; then EXTRA+=(--cases "$LAYER1_COMPARISON_CASE"); fi
"$CLIENT_ENV/bin/python" -u scripts/remote/compare_layer1_runtime.py "${EXTRA[@]}" \
  --official-source /hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade/server.py \
  --tokenizer "$CHECKPOINT/tokenizer/tokenizer.json" --model-url http://127.0.0.1:18806 \
  --manifest "$WORD_MANIFEST" \
  --output "$OUTPUT/comparison" > "$OUTPUT/client.log" 2>&1
