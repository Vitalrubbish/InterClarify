#!/usr/bin/env bash
# Run the X2Streaming-ASR real-time probe in one scheduler-assigned 4090.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
SOURCE="${SOULX_SOURCE:?set frozen source directory}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
ASSETS="$HOME/turncontrol-comparison"
ASR_PREFIX="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
MODEL="${SOULX_X2_MODEL:-$ASSETS/models/x2streaming-asr}"
MANIFEST="${SOULX_FDB_MANIFEST:?set frozen manifest}"
CONFIG="$SOURCE/configs/x2_streaming_probe.json"
[[ -f "$ASR_PREFIX/conda-meta/history" ]] || exit 2
[[ -f "$MODEL/model.safetensors" ]] || exit 2
[[ -f "$MANIFEST" ]] || exit 2
mkdir -p "$ROOT/runs"
exec 9>"$ROOT/.x2-streaming.lock"
flock -n 9 || exit 2
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
[[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ]] || exit 2
ulimit -f 262144
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 MPLBACKEND=Agg CUDA_MODULE_LOADING=LAZY
export TMPDIR="$RUN/tmp" XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface"
mkdir -p "$TMPDIR" "$HF_HOME"
cleanup() {
  code=$?
  trap - EXIT
  printf '%s\n' "$code" > "$RUN/exit_code.txt"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM
sha256sum "$SOURCE"/scripts/remote/x2_streaming_probe.py "$CONFIG" \
  "$SOURCE"/scripts/runtime/shared_context.py > "$RUN/source.sha256"
cp "$MANIFEST" "$RUN/frozen_manifest.json"
sha256sum "$RUN/frozen_manifest.json" >> "$RUN/source.sha256"
read -r EXPECTED_SHA EXPECTED_REVISION < <("$ASR_PREFIX/bin/python" - "$CONFIG" <<'PY'
import json
import sys
config = json.load(open(sys.argv[1]))
print(config['model']['sha256'], config['model']['revision'])
PY
)
ACTUAL_SHA="$(sha256sum "$MODEL/model.safetensors" | awk '{print $1}')"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || { echo 'Model weight digest differs' >&2; exit 2; }
printf 'model_sha256 %s\nmodel_revision %s\n' "$ACTUAL_SHA" "$EXPECTED_REVISION" > "$RUN/model.sha256"
PROBE=("$SOURCE/scripts/remote/x2_streaming_probe.py"
  --manifest "$RUN/frozen_manifest.json" --model "$MODEL"
  --output "$RUN/probe" --config "$CONFIG")
[[ "${SOULX_X2_CASE:-}" == "" ]] || PROBE+=(--case "$SOULX_X2_CASE")
[[ "${SOULX_X2_SKIP_CONTINUOUS:-0}" == 0 ]] || PROBE+=(--skip-continuous)
[[ "${SOULX_X2_CONTRACT_ONLY:-0}" == 0 ]] || PROBE+=(--contract-only)
timeout --signal=TERM --kill-after=20s 1700s \
  "$ASR_PREFIX/bin/python" -B "${PROBE[@]}" > "$RUN/probe.log" 2>&1 &
MODEL_PID=$!
STARTED=$SECONDS
while kill -0 "$MODEL_PID" 2>/dev/null; do
  (( SECONDS - STARTED < 1750 )) || { kill -TERM "$MODEL_PID" 2>/dev/null || true; exit 124; }
  [[ "$(du -sk "$RUN" | awk 'NR==1 {print $1}')" -le 262144 ]] || {
    kill -TERM "$MODEL_PID" 2>/dev/null || true
    exit 2
  }
  GPU_MIB=$(nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits \
    | awk -F, -v target="$MODEL_PID" '$1+0==target {sum+=$2} END {print sum+0}')
  printf '%s %s\n' "$SECONDS" "$GPU_MIB" >> "$RUN/gpu_memory_mib.txt"
  (( GPU_MIB <= 22528 )) || {
    kill -TERM "$MODEL_PID" 2>/dev/null || true
    exit 2
  }
  sleep 2
done
MODEL_CODE=0
wait "$MODEL_PID" || MODEL_CODE=$?
[[ -f "$RUN/probe/result.json" ]] || exit "$MODEL_CODE"
exit "$MODEL_CODE"
