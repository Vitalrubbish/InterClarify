#!/usr/bin/env bash
# Run a gated TTS component baseline on one scheduler-allocated GPU.
set -euo pipefail
TASK_ROOT="${TTS_TASK_ROOT:?set independent checkout}"
OUTPUT="${TTS_OUTPUT:?set a new output directory}"
ROUND1="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:-$ROUND1/models}"
REFERENCE="${TTS_REFERENCE:-$ROUND1/audio/reference.wav}"
CLIENT_ENV="${TTS_CLIENT_ENV:-xtalk-round1-client}"
MOSS_ENV="${TTS_MOSS_ENV:-xtalk-round1-moss}"
PORT="${TTS_PORT:-18004}"
source "${CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
mkdir -p "$OUTPUT"
cd "$TASK_ROOT"
export PYTHONNOUSERSITE=1 TOKENIZERS_PARALLELISM=false
export PYTHONPATH="$ROUND1/xtalk/src:$TASK_ROOT/scripts/remote"
export XTALK_ROUND1_ROOT="$ROUND1"
export XTALK_MOSS_SERVICE_ROOT="${XTALK_MOSS_SERVICE_ROOT:-$ROUND1/moss-service}"
export XTALK_MOSS_SOURCE_ROOT="${XTALK_MOSS_SOURCE_ROOT:-$ROUND1/moss-source}"
export XTALK_TTS_TRACE="$OUTPUT/server.jsonl"
export XTALK_TTS_METRICS=1 XTALK_TTS_SEED=17
export XTALK_TTS_STACK_DIAGNOSTIC="${TTS_STACK_DIAGNOSTIC:-0}"
export XTALK_TTS_GENERATION_BATCH_FRAMES="${TTS_BATCH_FRAMES:-0}"
export XTALK_TTS_EARLY_COMPILE="${TTS_EARLY_COMPILE:-0}"
export XTALK_TTS_LOCAL_ATTN=sdpa XTALK_TTS_LOCAL_COMPILE=inductor XTALK_TTS_SAMPLE=upstream
export TORCHINDUCTOR_CACHE_DIR="$OUTPUT/cache/inductor" TRITON_CACHE_DIR="$OUTPUT/cache/triton"
export TMPDIR="$OUTPUT/tmp"
mkdir -p "$TORCHINDUCTOR_CACHE_DIR" "$TRITON_CACHE_DIR" "$TMPDIR"
SERVER_PID='' SAMPLER_PID=''
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [ -n "$SERVER_PID" ]; then
    kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 -- "-$SERVER_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [ -n "$SAMPLER_PID" ]; then
    kill "$SAMPLER_PID" 2>/dev/null || true
    wait "$SAMPLER_PID" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
{
  date -u
  hostname
  git rev-parse HEAD
  git status --short
  conda env list
  printf 'CUDA_VISIBLE_DEVICES=%s\n' "${CUDA_VISIBLE_DEVICES:-unset}"
  nvidia-smi --query-gpu=uuid,name,driver_version,memory.total --format=csv
  sha256sum "$REFERENCE" scripts/remote/moss_tts_patch.py scripts/remote/moss_tts_service_patch.py
  for root in "$XTALK_MOSS_SOURCE_ROOT" "$XTALK_MOSS_SERVICE_ROOT" "$ROUND1/xtalk"; do
    git -C "$root" rev-parse HEAD
    git -C "$root" diff --quiet HEAD
  done
} > "$OUTPUT/environment.txt" 2>&1
cp "$MODEL_ROOT/models.lock.json" "$OUTPUT/models.lock.json"
cp configs/xtalk_round1.yaml "$OUTPUT/config.yaml"
conda run --no-capture-output -n "$MOSS_ENV" python scripts/remote/run_xtalk_round1.py --model-root "$MODEL_ROOT" check-deps --role tts > "$OUTPUT/dependencies.json" 2>&1
# The pinned upstream package is needed for the existing loop-equivalence cases.
XTALK_TTS_METRICS=0 XTALK_TTS_TRACE= XTALK_TTS_LOCAL_COMPILE=off XTALK_TTS_LOCAL_ATTN=upstream \
XTALK_TTS_EARLY_COMPILE=0 XTALK_TTS_GENERATION_BATCH_FRAMES=0 \
PYTHONPATH="$XTALK_MOSS_SOURCE_ROOT/moss_tts_realtime:$PYTHONPATH" \
  conda run --no-capture-output -n "$MOSS_ENV" python -m unittest discover -s tests -p 'test_*tts*.py' -q > "$OUTPUT/component_tests.log" 2>&1
nvidia-smi --query-gpu=timestamp,uuid,name,memory.used,utilization.gpu --format=csv -l 1 > "$OUTPUT/gpu.csv" 2>&1 &
SAMPLER_PID=$!
# setsid gives this job sole ownership of its service process group.
setsid conda run --no-capture-output -n "$CLIENT_ENV" python scripts/remote/run_xtalk_round1.py \
  --model-root "$MODEL_ROOT" serve tts --gpu-index 0 --port "$PORT" > "$OUTPUT/service.log" 2>&1 &
SERVER_PID=$!
conda run --no-capture-output -n "$CLIENT_ENV" python - "$PORT" "$SERVER_PID" "${TTS_HEALTH_TIMEOUT:-600}" <<'PY'
import os
import sys
import time
import urllib.request
port, pid, timeout = map(int, sys.argv[1:])
for _ in range(timeout):
    os.kill(pid, 0)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        time.sleep(1)
else:
    raise TimeoutError('TTS health did not become ready')
PY
BENCH=(conda run --no-capture-output -n "$CLIENT_ENV" python scripts/remote/tts_latency_benchmark.py)
"${BENCH[@]}" --prepare-corpus "$OUTPUT/corpus.jsonl"
# A long cold probe crosses the existing 50-frame compile gate.
conda run --no-capture-output -n "$CLIENT_ENV" python - "$OUTPUT/corpus.jsonl" "$OUTPUT/cold.jsonl" <<'PY'
import json
import pathlib
import sys
rows = pathlib.Path(sys.argv[1]).read_text().splitlines()
pathlib.Path(sys.argv[2]).write_text(rows[-1] + '\n')
PY
for probe in cold warm_one warm_two; do
  corpus="$OUTPUT/corpus.jsonl"
  if [ "$probe" = cold ]; then corpus="$OUTPUT/cold.jsonl"; fi
  "${BENCH[@]}" --probe --corpus "$corpus" --reference "$REFERENCE" \
    --url "ws://127.0.0.1:$PORT/tts/ws" --timeout 600 --output "$OUTPUT/$probe" > "$OUTPUT/$probe.log" 2>&1
done
conda run --no-capture-output -n "$CLIENT_ENV" python scripts/remote/run_xtalk_round1.py --model-root "$MODEL_ROOT" \
  tts-smoke --reference "$REFERENCE" --output "$OUTPUT/xtalk_smoke" --url "http://127.0.0.1:$PORT" \
  --gap-seconds 0.1 --timeout-seconds 600 --text 'Would you like the earlier train?' --text ' Please confirm your destination.' \
  > "$OUTPUT/xtalk_smoke.log" 2>&1
"${BENCH[@]}" --corpus "$OUTPUT/corpus.jsonl" --reference "$REFERENCE" \
  --url "ws://127.0.0.1:$PORT/tts/ws" --timeout 120 --repeats 3 \
  --server-trace "$XTALK_TTS_TRACE" --output "$OUTPUT/baseline" > "$OUTPUT/baseline.log" 2>&1
printf 'TTS component baseline finished: %s\n' "$OUTPUT"
