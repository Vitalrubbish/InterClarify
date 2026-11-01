#!/usr/bin/env bash
# Run one bounded, synchronized X2/SoulX comparison on a scheduler-assigned card.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
SOURCE="${SOULX_SOURCE:?set frozen source}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
ASSETS="$HOME/turncontrol-comparison"
ASR="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
SOULX="$ASSETS/envs/soulx"
for prefix in "$ASR" "$SOULX"; do [[ -f "$prefix/conda-meta/history" ]] || exit 2; done
exec 9>"$ROOT/.frontend-replay.lock"
flock -n 9 || exit 2
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
[[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 1048576 ]] || exit 2
ulimit -f 131072
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 CUDA_MODULE_LOADING=LAZY
export TMPDIR="$RUN/tmp" XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface" MPLBACKEND=Agg
mkdir -p "$TMPDIR" "$HF_HOME"
RPC_DIR=$(mktemp -d /tmp/pt-x2-XXXXXXXX)
SOCKET="$RPC_DIR/asr.sock"
ASR_PID=''
MODEL_PID=''
cleanup() {
  code=$?
  trap - EXIT
  for pid in "$MODEL_PID" "$ASR_PID"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
  rm -rf "$RPC_DIR"
  printf '%s\n' "$code" > "$RUN/exit_code.txt"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM
export SOULX_SOURCE_COMMIT
SOULX_SOURCE_COMMIT=$(git -C "$SOURCE" rev-parse HEAD)
sha256sum "$SOURCE"/scripts/runtime/{shared_context,x2_teacher_frontend,nemotron_teacher_frontend}.py \
  "$SOURCE"/scripts/remote/{x2_streaming_probe,x2_teacher_worker,x2_teacher_fdb}.py \
  "$SOURCE/configs/x2_teacher_append_only.json" > "$RUN/source.sha256"
cp "${SOULX_FDB_MANIFEST:?set frozen FDB30 manifest}" "$RUN/frozen_manifest.json"
sha256sum "$RUN/frozen_manifest.json" >> "$RUN/source.sha256"
STARTED=$SECONDS
"$ASR/bin/python" -B "$SOURCE/scripts/remote/x2_teacher_worker.py" \
  --model "$ASSETS/models/x2streaming-asr" \
  --upstream "$ASSETS/upstream/frozen-20261028/x2streaming-asr" \
  --config "$SOURCE/configs/x2_teacher_append_only.json" \
  --warmup-audio "$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
  --socket "$SOCKET" --output "$RUN/asr_ready.json" > "$RUN/asr.log" 2>&1 &
ASR_PID=$!
while [[ ! -S "$SOCKET" ]]; do
  kill -0 "$ASR_PID" 2>/dev/null || { wait "$ASR_PID"; exit 2; }
  (( SECONDS-STARTED < 300 )) || exit 124
  sleep 1
done
PROBE=("$SOURCE/scripts/remote/x2_teacher_fdb.py" run --manifest "$RUN/frozen_manifest.json")
[[ "${SOULX_TEACHER_SMOKE:-0}" == 0 ]] || PROBE+=(--smoke)
"$SOULX/bin/python" -B "${PROBE[@]}" --assets "$ASSETS" \
  --check-source "$ASSETS/source/6de0d70" --socket "$SOCKET" --output "$RUN/probe" > "$RUN/probe.log" 2>&1 &
MODEL_PID=$!
while kill -0 "$MODEL_PID" 2>/dev/null; do
  (( SECONDS-STARTED < 1700 )) || exit 124
  usage=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  printf '%s %s\n' "$SECONDS" "$usage" >> "$RUN/gpu_memory_mib.txt"
  size=$(du -sk "$RUN" | awk '{print $1}')
  if (( usage > 22528 || size > 131072 )); then
    printf 'resource_stop gpu_mib=%s output_kib=%s\n' "$usage" "$size" > "$RUN/resource_stop.txt"
    exit 2
  fi
  sleep 1
done
MODEL_CODE=0
wait "$MODEL_PID" || MODEL_CODE=$?
"$SOULX/bin/python" -B "$SOURCE/scripts/remote/x2_teacher_fdb.py" analyze \
  --probe "$RUN/probe" --output "$RUN/analysis" \
  --baseline "$ROOT/runs/ntf010-teacher-fdb30-20261101-r6" > "$RUN/analysis.log" 2>&1
exit "$MODEL_CODE"
