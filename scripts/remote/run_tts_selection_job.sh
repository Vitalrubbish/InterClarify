#!/usr/bin/env bash
# Run one candidate on an allocated GPU, with an isolated service process group.
set -euo pipefail
ROOT="${TTS_SELECTION_ROOT:?set shared experiment root}"
BACKEND="${TTS_BACKEND:?set candidate}"
OUTPUT="${TTS_SELECTION_OUTPUT:-$ROOT/runs/$BACKEND}"
[ ! -e "$OUTPUT" ] || { echo "Output exists: $OUTPUT" >&2; exit 2; }
mkdir -p "$OUTPUT"
cd "$ROOT"
export PYTHONNOUSERSITE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
export HF_HUB_DOWNLOAD_TIMEOUT=120 HF_HUB_ETAG_TIMEOUT=20
ENV="$ROOT/envs/pocket"
CLIENT="/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-round1-client/bin/python"
PORT=18761
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
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$OUTPUT/gpu.txt" 2>&1 || true
lscpu > "$OUTPUT/cpu.txt"
cp scripts/tts_selection_benchmark.py "$OUTPUT/benchmark_source.py"
sha256sum scripts/tts_selection_benchmark.py configs/tts_selection_texts.csv > "$OUTPUT/source.sha256"
ARGS=(--backend "$BACKEND" --port "$PORT" --threads 2)
if [ "$BACKEND" = pocket ]; then ARGS+=(--device cpu); fi
if [ "$BACKEND" = kyutai ]; then
  ENV=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/envs/kyutai
  export HF_HUB_CACHE=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-kyutai/hf-py-cache
  export HF_HUB_OFFLINE=1
  ARGS+=(--voice "$HF_HUB_CACHE/models--kyutai--tts-voices/snapshots/323332d33f997de8394f24a193e1a76df720e01a/expresso/ex03-ex01_happy_001_channel1_334s.wav.1e68beda@240.safetensors")
elif [ "$BACKEND" != moss ]; then
  export HF_HOME="$ROOT/models/hf"
fi
if [ "$BACKEND" = moss ]; then
  PORT=18004
  export PATH="/opt/conda/bin:$PATH"
  export XTALK_MOSS_SERVICE_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/moss-service
  export XTALK_MOSS_SOURCE_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/moss-source
  export XTALK_TTS_LOCAL_ATTN=sdpa XTALK_TTS_LOCAL_COMPILE=inductor
  export TORCHINDUCTOR_CACHE_DIR="$OUTPUT/inductor" TRITON_CACHE_DIR="$OUTPUT/triton"
  export TMPDIR="$OUTPUT/tmp"
  mkdir -p "$TMPDIR"
  "/opt/conda/envs/xtalk-round1-moss/bin/python" -m pip freeze > "$OUTPUT/packages.txt"
  cp /hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/models/models.lock.json "$OUTPUT/models.lock.json"
  sha256sum /hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/audio/reference.wav > "$OUTPUT/voice.sha256"
  setsid "$CLIENT" -u source/scripts/remote/run_xtalk_round1.py --model-root /hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/models serve tts --gpu-index 0 --port "$PORT" > "$OUTPUT/service.log" 2>&1 &
else
  setsid "$ENV/bin/python" -u scripts/tts_selection_benchmark.py serve "${ARGS[@]}" > "$OUTPUT/service.log" 2>&1 &
fi
SERVER=$!
"$CLIENT" - "$PORT" "$SERVER" <<'PYCODE'
import os, sys, time, urllib.request
for _ in range(600):
    os.kill(int(sys.argv[2]), 0)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{sys.argv[1]}/health', timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        time.sleep(1)
else:
    raise TimeoutError('Model service did not start')
PYCODE
"$CLIENT" -u scripts/tts_selection_benchmark.py run --backend "$BACKEND" --port "$PORT" --output "$OUTPUT/measurements" > "$OUTPUT/client.log" 2>&1
