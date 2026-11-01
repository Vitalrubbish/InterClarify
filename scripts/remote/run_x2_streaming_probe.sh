#!/usr/bin/env bash
# Run one bounded offline X2 probe on a scheduler-assigned GPU.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
SOURCE="${SOULX_SOURCE:?set frozen source directory}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
PREFIX="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
[[ -f "$PREFIX/conda-meta/history" ]] || exit 2
mkdir -p "$ROOT/runs"
exec 9>"$ROOT/.frontend-replay.lock"
flock -n 9 || exit 2
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
[[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 1048576 ]] || exit 2
ulimit -f 262144
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 CUDA_MODULE_LOADING=LAZY
export TMPDIR="$RUN/tmp" XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface"
mkdir -p "$TMPDIR" "$HF_HOME"
MODEL_PID=''
MONITOR_PID=''
cleanup() {
  code=$?
  trap - EXIT
  for pid in "$MODEL_PID" "$MONITOR_PID"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
  printf '%s\n' "$code" > "$RUN/exit_code.txt"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM
cp "${SOULX_FDB_MANIFEST:?set frozen manifest}" "$RUN/frozen_manifest.json"
sha256sum "$SOURCE/scripts/remote/x2_streaming_probe.py" \
  "$SOURCE/scripts/remote/run_x2_streaming_probe.sh" "$SOURCE/configs/x2_streaming_probe.json" \
  "$RUN/frozen_manifest.json" > "$RUN/source.sha256"
git -C "$SOURCE" rev-parse HEAD > "$RUN/source_commit.txt"
export SOULX_SOURCE_COMMIT
SOULX_SOURCE_COMMIT=$(cat "$RUN/source_commit.txt")
timeout --signal=TERM --kill-after=15 1740 "$PREFIX/bin/python" -B \
  "$SOURCE/scripts/remote/x2_streaming_probe.py" \
  --model "$HOME/turncontrol-comparison/models/x2streaming-asr" \
  --upstream "$HOME/turncontrol-comparison/upstream/frozen-20261028/x2streaming-asr" \
  --manifest "$RUN/frozen_manifest.json" --config "$SOURCE/configs/x2_streaming_probe.json" \
  --output "$RUN/probe" > "$RUN/probe.log" 2>&1 &
MODEL_PID=$!
(
  while kill -0 "$MODEL_PID" 2>/dev/null; do
    usage=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
    printf '%s %s\n' "$(date +%s)" "$usage" >> "$RUN/gpu_memory_mib.txt"
    size=$(du -sk "$RUN" | awk '{print $1}')
    if (( usage > 22528 || size > 262144 )); then
      printf 'resource_stop gpu_mib=%s output_kib=%s\n' "$usage" "$size" > "$RUN/resource_stop.txt"
      kill -TERM "$MODEL_PID" 2>/dev/null || true
      break
    fi
    sleep 1
  done
) &
MONITOR_PID=$!
wait "$MODEL_PID"
