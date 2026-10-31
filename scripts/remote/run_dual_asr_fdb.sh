#!/usr/bin/env bash
# Run independent RNNT and native SenseVoice/SoulX on one scheduler-assigned card.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
SOURCE="${SOULX_SOURCE:?set frozen source directory}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
ASSETS="$HOME/turncontrol-comparison"
ASR_PREFIX="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
SOULX_PREFIX="$ASSETS/envs/soulx"
for prefix in "$ASR_PREFIX" "$SOULX_PREFIX"; do [[ -f "$prefix/conda-meta/history" ]] || exit 2; done
mkdir -p "$ROOT/runs"
exec 9>"$ROOT/.frontend-replay.lock"
flock -n 9 || exit 2
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
[[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ]] || exit 2
ulimit -f 131072
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 MPLBACKEND=Agg CUDA_MODULE_LOADING=LAZY
export TMPDIR="$RUN/tmp" XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface"
mkdir -p "$TMPDIR" "$HF_HOME"
# Unix paths are length-limited; the private directory prevents collisions.
RPC_DIR=$(mktemp -d /tmp/pt-ns-XXXXXXXX)
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
sha256sum "$SOURCE"/scripts/runtime/{shared_context,sensevoice_transcript,soulx_frontend,dual_asr_frontend}.py \
  "$SOURCE"/scripts/remote/{nemotron_asr_service,nemotron_teacher_worker,nemotron_teacher_fdb,dual_asr_worker,dual_asr_fdb}.py > "$RUN/source.sha256"
cp "${SOULX_FDB_MANIFEST:?set frozen manifest}" "$RUN/frozen_manifest.json"
sha256sum "$RUN/frozen_manifest.json" >> "$RUN/source.sha256"
PROBE=("$SOURCE/scripts/remote/dual_asr_fdb.py" run --manifest "$RUN/frozen_manifest.json")
[[ "${SOULX_DUAL_SMOKE:-0}" == 0 ]] || PROBE+=(--smoke)
"$ASR_PREFIX/bin/python" -B "$SOURCE/scripts/remote/dual_asr_worker.py" \
  --model "$HOME/interclarify-asr-selection/models/nemotron_en" \
  --warmup-audio "$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
  --socket "$SOCKET" --output "$RUN/asr_ready.json" > "$RUN/asr.log" 2>&1 &
ASR_PID=$!
STARTED=$SECONDS
while [[ ! -S "$SOCKET" ]]; do
  kill -0 "$ASR_PID" 2>/dev/null || { wait "$ASR_PID"; exit 2; }
  (( SECONDS - STARTED < 300 )) || exit 124
  sleep 1
done
"$SOULX_PREFIX/bin/python" -B "${PROBE[@]}" \
  --assets "$ASSETS" --check-source "$ASSETS/source/6de0d70" --socket "$SOCKET" \
  --output "$RUN/probe" > "$RUN/probe.log" 2>&1 &
MODEL_PID=$!
while kill -0 "$MODEL_PID" 2>/dev/null; do
  (( SECONDS - STARTED < 1700 )) || exit 124
  [[ "$(du -sk "$RUN" | awk 'NR==1 {print $1}')" -le 131072 ]] || exit 2
  GPU_MIB=$(nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits | awk -F, -v first="$ASR_PID" -v second="$MODEL_PID" '$1+0==first || $1+0==second {sum+=$2} END {print sum+0}')
  printf '%s %s\n' "$SECONDS" "$GPU_MIB" >> "$RUN/gpu_memory_mib.txt"
  RSS_KIB=$(ps -o rss= -p "$ASR_PID,$MODEL_PID" | awk '{sum+=$1} END {print sum+0}')
  printf '%s %s\n' "$SECONDS" "$RSS_KIB" >> "$RUN/rss_kib.txt"
  (( RSS_KIB <= 33554432 )) || exit 2
  (( GPU_MIB <= 22528 )) || exit 2
  sleep 2
done
MODEL_CODE=0
wait "$MODEL_PID" || MODEL_CODE=$?
"$SOULX_PREFIX/bin/python" -B "$SOURCE/scripts/remote/dual_asr_fdb.py" analyze \
  --probe "$RUN/probe" --output "$RUN/analysis" > "$RUN/analysis.log" 2>&1
exit "$MODEL_CODE"
