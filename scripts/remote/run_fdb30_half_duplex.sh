#!/usr/bin/env bash
# Run isolated half-duplex services and native dual frontend in one scheduled job.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
SOURCE="${SOULX_SOURCE:?set frozen source}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
MODE="${SOULX_MODE:-smoke}"
[[ "$MODE" == smoke || "$MODE" == formal ]] || exit 2
[[ "$RUN_ID" =~ ^[A-Za-z0-9_-]{1,70}$ ]] || exit 2
[[ -n "${JobID:-}" || -n "${NVIDIA_VISIBLE_DEVICES:-}" ]] || exit 2
if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  IFS=',' read -r -a DEVICES <<< "$CUDA_VISIBLE_DEVICES"
else
  mapfile -t DEVICES < <(nvidia-smi --query-gpu=index --format=csv,noheader,nounits)
fi
ASSIGNED_DEVICES=$(IFS=,; echo "${DEVICES[*]}")
[[ "${#DEVICES[@]}" == 3 ]] || exit 2
ASSETS="$HOME/turncontrol-comparison"
FRONTEND="$ASSETS/envs/soulx/bin/python"
QWEN="$HOME/interclarify-xturnix-fleurs/envs/xturnix/bin/python"
TTS="$ASSETS/envs/indextts/bin/python"
ASR="$HOME/interclarify-english-integration-20261018-v1/envs/asr/bin/python"
for executable in "$FRONTEND" "$QWEN" "$TTS" "$ASR"; do
  [[ -f "${executable%/bin/python}/conda-meta/history" ]] || exit 2
done
RUN="$ROOT/runs/$RUN_ID"
mkdir -p "$ROOT/runs"
mkdir "$RUN"
exec 9>"$ROOT/.half-duplex.lock"
flock -n 9 || exit 2
ulimit -f 1048576
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MODELSCOPE_OFFLINE=1 PIP_NO_INDEX=1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export MPLBACKEND=Agg CUDA_MODULE_LOADING=LAZY
export XDG_CACHE_HOME="$RUN/cache" TMPDIR="$RUN/tmp"
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR"
SOCKETS=$(mktemp -d /tmp/pt-half-XXXXXXXX)
PIDS=()
cleanup() {
  code=$?
  trap - EXIT
  for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  sleep 2
  for pid in "${PIDS[@]}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
  wait || true
  printf '%s\n' "$code" > "$RUN/exit_code.txt"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 143' INT TERM
WARMUP="$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav"
"$FRONTEND" - "$WARMUP" "$RUN" <<'PY'
import sys,hashlib,json
from pathlib import Path
import numpy as np
import soundfile as sf
source, out = map(Path,sys.argv[1:])
assert hashlib.sha256(source.read_bytes()).hexdigest()=='d733a878fbb3393dac0349cfa1293e4fad9a8bd5ec1f58ce6adc019de4b94f32'
audio,rate=sf.read(source,dtype='float32')
gain=min(.05/float(np.sqrt(np.mean(audio.astype(np.float64)**2))),.9/float(np.max(np.abs(audio))))
voice=out/'english-reference.wav'
sf.write(voice,audio*gain,rate,subtype='PCM_16')
value=hashlib.sha256(voice.read_bytes()).hexdigest()
assert value=='59165c19423723c60fcd5549a89a3c5f25040b276f3cb27f100051a8ed3d3187',value
(out/'voice.json').write_text(json.dumps({'sha256':value,'source':str(source),'gain':gain},indent=2)+'\n')
PY
for backend in qwen indextts; do
  executable="$QWEN"; device="${DEVICES[1]}"
  if [[ "$backend" == indextts ]]; then executable="$TTS"; device="${DEVICES[2]}"; fi
  CUDA_VISIBLE_DEVICES="$device" setsid "$executable" -B "$SOURCE/scripts/remote/generation_worker.py" \
    --backend "$backend" --root "$ASSETS" --upstream "$ASSETS/upstream/frozen-20261028" \
    --output "$RUN/$backend" --socket "$SOCKETS/$backend.sock" \
    --voice "$RUN/english-reference.wav" --memory-fraction .83 > "$RUN/$backend.log" 2>&1 &
  PIDS+=("$!")
done
for ((i=0;i<300;i++)); do
  [[ ! -f "$RUN/qwen/ready.json" || ! -f "$RUN/indextts/ready.json" ]] || break
  for pid in "${PIDS[@]}"; do kill -0 "$pid" || exit 1; done
  sleep 2
done
[[ -f "$RUN/qwen/ready.json" && -f "$RUN/indextts/ready.json" ]] || exit 1
ARGS=()
[[ "$MODE" != smoke ]] || ARGS+=(--smoke)
CUDA_VISIBLE_DEVICES="${DEVICES[0]}" setsid "$FRONTEND" -B "$SOURCE/scripts/remote/fdb30_half_duplex.py" \
  --manifest "$ROOT/manifests/fdb30-20261030-r1.json" --assets "$ASSETS" \
  --upstream "$ROOT/upstream/soulx-duplug" --asr-python "$ASR" --warmup-audio "$WARMUP" \
  --output "$RUN/frontend" --socket-root "$SOCKETS" "${ARGS[@]}" > "$RUN/frontend.log" 2>&1 &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")
STARTED=$SECONDS
while kill -0 "$FRONTEND_PID" 2>/dev/null; do
  size=$(du -sk "$RUN" | cut -f1)
  gpu_peak=$(nvidia-smi --id="$ASSIGNED_DEVICES" --query-gpu=memory.used --format=csv,noheader,nounits | sort -nr | head -1)
  printf '%s %s %s\n' "$SECONDS" "$size" "$gpu_peak" >> "$RUN/resources.txt"
  if (( gpu_peak > 22528 )); then
    printf 'gpu_peak_mib=%s\n' "$gpu_peak" > "$RUN/resource_stop.txt"
    exit 1
  fi
  if (( size > 2097152 || SECONDS-STARTED > 6600 )); then
    printf 'output_kib=%s seconds=%s\n' "$size" "$((SECONDS-STARTED))" > "$RUN/resource_stop.txt"
    exit 1
  fi
  sleep 5
done
wait "$FRONTEND_PID"
