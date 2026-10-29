#!/usr/bin/env bash
# Run one bounded audio-to-Context replay in the scheduler-assigned GPU process.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
ASSET_ROOT="${SOULX_ASSET_ROOT:-$HOME/turncontrol-comparison}"
SOURCE="${SOULX_SOURCE:?set frozen source directory}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
MANIFEST="${SOULX_AUDIO_MANIFEST:?set frozen audio manifest}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
PREFIX="$ASSET_ROOT/envs/soulx"
[[ -f "$PREFIX/conda-meta/history" ]] || exit 2
mkdir -p "$ROOT/runs"
exec 9>"$ROOT/.frontend-replay.lock"
flock -n 9 || exit 2
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
trap 'code=$?; printf "%s\n" "$code" > "$RUN/exit_code.txt"' EXIT
[[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ]] || exit 2
ulimit -f 131072
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
export MPLBACKEND=Agg CUDA_MODULE_LOADING=LAZY
export XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface" TMPDIR="$RUN/tmp"
mkdir -p "$TMPDIR" "$HF_HOME"
cp "$MANIFEST" "$RUN/audio_manifest.json"
sha256sum "$SOURCE"/scripts/runtime/{shared_context,sensevoice_transcript,soulx_frontend}.py \
  "$SOURCE/scripts/remote/soulx_frontend_replay.py" "$MANIFEST" > "$RUN/source.sha256"
"$PREFIX/bin/python" -B "$SOURCE/scripts/remote/soulx_frontend_replay.py" \
  --root "$ASSET_ROOT" --check-source "$ASSET_ROOT/source/6de0d70" \
  --manifest "$RUN/audio_manifest.json" --output "$RUN/replay" > "$RUN/replay.log" 2>&1 &
REPLAY_PID=$!
cleanup() { kill "$REPLAY_PID" 2>/dev/null || true; wait "$REPLAY_PID" 2>/dev/null || true; }
trap 'cleanup; code=1; printf "%s\n" "$code" > "$RUN/exit_code.txt"' TERM INT
STARTED=$SECONDS
while kill -0 "$REPLAY_PID" 2>/dev/null; do
  if (( SECONDS - STARTED > 1100 )); then cleanup; exit 124; fi
  if [[ "$(du -sk "$RUN" | awk '{print $1}')" -gt 131072 ]]; then cleanup; exit 2; fi
  GPU_MIB="$(nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits | awk -F, -v pid="$REPLAY_PID" '$1+0==pid {sum+=$2} END {print sum+0}')"
  printf '%s %s\n' "$SECONDS" "$GPU_MIB" >> "$RUN/gpu_memory_mib.txt"
  if (( GPU_MIB > 22528 )); then cleanup; exit 2; fi
  sleep 2
done
wait "$REPLAY_PID"
