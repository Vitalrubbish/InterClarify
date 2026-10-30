#!/usr/bin/env bash
# Run finite old/new pilot arms under a single scheduled resource allocation.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
ENV_DIR="${TEXTTURN_ENV:-$HOME/interclarify-xturnix-fleurs/envs/xturnix}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
DATA="$ROOT/dataset/tt-010-repair-20261027-r5"
case "$RUN_ID" in *[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
[ ! -e "$ROOT/runs/$RUN_ID" ] && [ -f "$ENV_DIR/conda-meta/history" ] || exit 2
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || exit 2
export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8
export TOKENIZERS_PARALLELISM=false PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p "$ROOT/submit_logs"
LOG="$ROOT/submit_logs/$RUN_ID.training.log"
git -C "$REPO_ROOT" rev-parse HEAD > "$ROOT/submit_logs/$RUN_ID.source_commit.txt"
"$ENV_DIR/bin/python" -m pip freeze > "$ROOT/submit_logs/$RUN_ID.packages.txt"
setsid "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/training/train_textturn_pilot.py" \
  --model "$ROOT/models/qwen3-0.6b" --old-data "$ROOT/dataset/tt-010-fulltraj-r1" \
  --data "$DATA" --config "$REPO_ROOT/configs/textturn_repair_pilot.json" \
  --output "$ROOT/runs/$RUN_ID" > "$LOG" 2>&1 &
TASK_PID=$!
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [ -n "$TASK_PID" ]; then
    kill -TERM -- "-$TASK_PID" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$TASK_PID" 2>/dev/null || true
    wait "$TASK_PID" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$ROOT/submit_logs/$RUN_ID.exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
while kill -0 "$TASK_PID" 2>/dev/null; do
  GPU_MIB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  ASSET_BYTES=$(du -sb "$ROOT/models" "$ROOT/dataset" "$ROOT/runs" | awk '{n+=$1} END {printf "%.0f\n", n}')
  REPORT_BYTES=$(du -sb "$ROOT/runs" | awk '{print $1}')
  FREE_KIB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
  printf '%s %s %s %s %s\n' "$(date -u +%FT%TZ)" "$GPU_MIB" "$ASSET_BYTES" "$REPORT_BYTES" "$FREE_KIB" >> "$ROOT/submit_logs/$RUN_ID.resources.txt"
  if [ "$GPU_MIB" -ge 22528 ] || [ "$ASSET_BYTES" -ge 10737418240 ] || [ "$REPORT_BYTES" -ge 2147483648 ] || [ "$FREE_KIB" -lt 31457280 ]; then
    echo 'Resource stop line exceeded' >> "$LOG"
    exit 3
  fi
  sleep 10
done
set +e
wait "$TASK_PID"
RC=$?
set -e
TASK_PID=''
exit "$RC"
