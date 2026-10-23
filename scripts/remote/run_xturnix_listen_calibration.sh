#!/usr/bin/env bash
# Run a frozen Listen calibration or pause diagnostic in one bounded GPU job.
set -euo pipefail

ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
RUN_ID="${XTURNIX_CAL_RUN_ID:?set a unique run id}"
INPUTS="${XTURNIX_CAL_INPUTS:?set frozen input directory}"
ENTRYPOINT="${XTURNIX_CAL_ENTRYPOINT:-evaluate_xturnix_control.py}"
TIMEOUT_SECONDS="${XTURNIX_CAL_TIMEOUT_SECONDS:-1800}"
case "$ENTRYPOINT" in
  evaluate_xturnix_control.py|xturnix_pause_usage_probe.py) ;;
  *) echo "unsupported diagnostic entrypoint" >&2; exit 2 ;;
esac
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] && [ "$TIMEOUT_SECONDS" -ge 1 ] && [ "$TIMEOUT_SECONDS" -le 1800 ] || { echo "invalid job timeout" >&2; exit 2; }
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="$ROOT/envs/xturnix"
MODEL="$ROOT/models/xturnix-pt"
OUT="$ROOT/runs/$RUN_ID"
case "$RUN_ID" in
  *[!A-Za-z0-9._-]*|.*) echo "invalid calibration run id" >&2; exit 2 ;;
esac
[ ! -e "$OUT" ] || { echo "output already exists" >&2; exit 2; }
[ -f "$ENV_DIR/conda-meta/history" ] || { echo "missing conda environment" >&2; exit 2; }
[ -f "$INPUTS/prepare_summary.json" ] || { echo "missing frozen inputs" >&2; exit 2; }
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || { echo "less than 30 GiB free" >&2; exit 2; }
[ "$(du -sk "$INPUTS" | awk '{print $1}')" -le 10240 ] || { echo "input budget exceeded" >&2; exit 2; }
mkdir "$OUT"
exec > >(tee "$OUT/run.log") 2>&1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=8 MKL_NUM_THREADS=8
worker_pid=""
monitor_pid=""
cleanup() {
  rc=$?
  trap - EXIT
  if [ -n "$monitor_pid" ]; then kill "$monitor_pid" 2>/dev/null || true; wait "$monitor_pid" 2>/dev/null || true; fi
  if [ -n "$worker_pid" ] && kill -0 "$worker_pid" 2>/dev/null; then
    kill "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$OUT/exit_code.txt"
  du -sk "$OUT" > "$OUT/output_size_kib.txt"
  exit "$rc"
}
trap cleanup EXIT
git -C "$REPO_ROOT" rev-parse HEAD > "$OUT/source_commit.txt"
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$OUT/hardware.csv"
printf 'run_id=%s inputs=%s source=%s\n' "$RUN_ID" "$INPUTS" "$REPO_ROOT"
timeout --signal=TERM --kill-after=30s "$TIMEOUT_SECONDS" "$ENV_DIR/bin/python" -u \
  "$REPO_ROOT/scripts/remote/$ENTRYPOINT" \
  --inputs "$INPUTS" --output "$OUT/results" --model "$MODEL" \
  --model-lock "$ROOT/models/xturnix-pt.lock.json" &
worker_pid=$!
(
  while kill -0 "$worker_pid" 2>/dev/null; do
    sample="$(nvidia-smi --query-gpu=timestamp,memory.used --format=csv,noheader,nounits)"
    printf '%s\n' "$sample" >> "$OUT/gpu_samples.csv"
    used="$(printf '%s\n' "$sample" | awk -F, '{gsub(/ /,"",$2); if ($2>m) m=$2} END {print m+0}')"
    size="$(du -sk "$OUT" | awk '{print $1}')"
    if [ "$used" -gt 22528 ] || [ "$size" -gt 102400 ]; then
      printf 'resource_stop gpu_mib=%s output_kib=%s\n' "$used" "$size" > "$OUT/resource_stop.txt"
      kill "$worker_pid" 2>/dev/null || true
      break
    fi
    sleep 2
  done
) &
monitor_pid=$!
wait "$worker_pid"
worker_pid=""
