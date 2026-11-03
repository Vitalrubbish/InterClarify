#!/usr/bin/env bash
# Run one scheduler-bound NTF-018 job with fixed conditions and resource stops.
set -euo pipefail
ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
SOURCE="${SOULX_SOURCE:?set frozen clean source worktree}"
RUN_ID="${SOULX_RUN_ID:?set unique run ID}"
GROUP="${NTF_FRONTEND_GROUP:-${NTF018_GROUP:?set a frontend condition group}}"
MANIFEST="${SOULX_FDB_MANIFEST:?set original frozen FDB30 manifest}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
[[ "$GROUP" == dual || "$GROUP" == single || "$GROUP" == matrix || "$GROUP" == fdb-dual || "$GROUP" == fdb-single ]] || exit 2
[[ "${NTF_SCHEDULED_RUN:-0}" == 1 && -n "${CUDA_VISIBLE_DEVICES:-}" ]] || exit 2
ASSETS="$HOME/turncontrol-comparison"
SOULX="$ASSETS/envs/soulx/bin/python"
ASR="$HOME/interclarify-english-integration-20261018-v1/envs/asr/bin/python"
for python in "$SOULX" "$ASR"; do [[ -f "${python%/bin/python}/conda-meta/history" ]] || exit 2; done
[[ -z "$(git -C "$SOURCE" status --porcelain)" ]] || exit 2
[[ "$(sha256sum "$MANIFEST" | cut -d' ' -f1)" == 403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07 ]] || exit 2
mkdir -p "$ROOT/runs"
exec 9>"$ROOT/.frontend-replay.lock"
flock -n 9 || exit 2
[[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 10485760 ]] || exit 2
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
ulimit -f 131072
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MODELSCOPE_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 CUDA_MODULE_LOADING=LAZY MPLBACKEND=Agg
export TMPDIR="$RUN/tmp" XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface"
mkdir -p "$TMPDIR" "$HF_HOME"
cp "$MANIFEST" "$RUN/frozen_manifest.json"
git -C "$SOURCE" rev-parse HEAD > "$RUN/source_commit.txt"
git -C "$SOURCE" ls-files scripts/runtime scripts/remote/native_frontend_probe.py \
  scripts/remote/native_frontend_worker.py scripts/remote/x2_streaming_probe.py scripts/remote/run_native_frontend_probe.sh \
  scripts/remote/run_native_frontend_fdb.sh configs/native_soulx.json \
  configs/x2_streaming_probe.json | while IFS= read -r file; do sha256sum "$SOURCE/$file"; done > "$RUN/source.sha256"
printf '%s\n' "$GROUP" > "$RUN/group.txt"
PID=''
cleanup() {
  code=$?
  trap - EXIT
  if [[ -n "$PID" ]]; then
    kill -TERM -- "-$PID" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  printf '%s\n' "$code" > "$RUN/exit_code.txt"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM INT
STARTED=$SECONDS
CONDITIONS=(single-full)
[[ "$GROUP" != dual ]] || CONDITIONS=(dual-limited dual-full)
[[ "$GROUP" != matrix ]] || CONDITIONS=(dual-limited dual-full single-full)
SUITE_ARGS=()
if [[ "$GROUP" == fdb-dual || "$GROUP" == fdb-single ]]; then
  [[ "$GROUP" != fdb-dual ]] || CONDITIONS=(dual-full)
  cp "${NTF_ACCEPTANCE_GATE:?set accepted NTF-018 evidence}" "$RUN/ntf018_acceptance.json"
  sha256sum "$RUN/ntf018_acceptance.json" >> "$RUN/source.sha256"
  SUITE_ARGS=(--suite fdb30 --acceptance-gate "$RUN/ntf018_acceptance.json"
    --acceptance-gate-sha256 "${NTF_ACCEPTANCE_GATE_SHA256:?set frozen acceptance evidence digest}")
fi
FINAL_CODE=0
for condition in "${CONDITIONS[@]}"; do
  remaining=$((1750 - SECONDS + STARTED))
  (( remaining > 0 )) || exit 124
  setsid timeout --signal=TERM --kill-after=5 "$remaining" "$SOULX" -B \
    "$SOURCE/scripts/remote/native_frontend_probe.py" --condition "$condition" "${SUITE_ARGS[@]}" \
    --manifest "$RUN/frozen_manifest.json" --assets "$ASSETS" \
    --upstream "$ROOT/upstream/soulx-duplug" --asr-python "$ASR" \
    --warmup-audio "$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
    --output "$RUN/$condition" > "$RUN/$condition.log" 2>&1 &
  PID=$!
  while kill -0 "$PID" 2>/dev/null; do
    usage=$(nvidia-smi -i "${CUDA_VISIBLE_DEVICES%%,*}" --query-gpu=memory.used --format=csv,noheader,nounits)
    size=$(du -sk "$RUN" | awk '{print $1}')
    rss=$(ps -e -o pgid=,rss= | awk -v group="$PID" '$1==group {sum+=$2} END {print sum+0}')
    printf '%s %s %s %s %s\n' "$SECONDS" "$condition" "$usage" "$rss" "$size" >> "$RUN/resources.txt"
    if (( usage > 22528 || size > 131072 || rss > 33554432 || SECONDS - STARTED > 1750 )); then
      printf 'gpu_mib=%s output_kib=%s rss_kib=%s\n' "$usage" "$size" "$rss" > "$RUN/resource_stop.txt"
      exit 2
    fi
    sleep 1
  done
  CODE=0
  wait "$PID" || CODE=$?
  PID=''
  printf '%s\n' "$CODE" > "$RUN/$condition.exit_code.txt"
  # Limited warmup failures remain diagnostic evidence; full warmup must still be measured once.
  [[ "$CODE" == 0 ]] || FINAL_CODE=1
done
exit "$FINAL_CODE"
