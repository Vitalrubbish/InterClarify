#!/usr/bin/env bash
# Run one frozen TextTurn training job under the shared single-card budget.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
ENV_DIR="${TEXTTURN_ENV:-$HOME/interclarify-xturnix-fleurs/envs/xturnix}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
case "$RUN_ID" in *[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
RUN_DIR="$ROOT/runs/$RUN_ID"
[ ! -e "$RUN_DIR" ] || { echo 'Run already exists' >&2; exit 2; }
[ -f "$ENV_DIR/conda-meta/history" ] || { echo 'Missing conda environment' >&2; exit 2; }
mkdir -p "$ROOT/submit_logs"
FREE_KIB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
[ "$FREE_KIB" -ge 31457280 ] || { echo 'Need 30GiB free disk' >&2; exit 2; }
export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8
export TOKENIZERS_PARALLELISM=false PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
LOG="$ROOT/submit_logs/$RUN_ID.training.log"
git -C "$REPO_ROOT" rev-parse HEAD > "$ROOT/submit_logs/$RUN_ID.source_commit.txt"
"$ENV_DIR/bin/python" -m pip freeze > "$ROOT/submit_logs/$RUN_ID.packages.txt"
setsid timeout --signal=TERM --kill-after=30 13800 "$ENV_DIR/bin/python" -u \
  "$REPO_ROOT/scripts/training/train_textturn.py" \
  --model "$ROOT/models/qwen3-0.6b" --data "$ROOT/dataset/tt-001-frozen-r3" \
  --config "$REPO_ROOT/configs/textturn_training.json" --output "$RUN_DIR" > "$LOG" 2>&1 &
TRAIN_PID=$!
cleanup() {
  kill -TERM -- "-$TRAIN_PID" 2>/dev/null || true
  wait "$TRAIN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
while kill -0 "$TRAIN_PID" 2>/dev/null; do
  GPU_MIB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  ASSET_BYTES=$(du -sb "$ROOT/models" "$ROOT/dataset" "$ROOT/runs" | awk '{n+=$1} END {print n}')
  REPORT_BYTES=$(du -sb "$ROOT/runs" | awk '{print $1}')
  if [ "$GPU_MIB" -ge 22528 ] || [ "$ASSET_BYTES" -ge 10737418240 ] || [ "$REPORT_BYTES" -ge 2147483648 ]; then
    echo "Resource stop: gpu_mib=$GPU_MIB asset_bytes=$ASSET_BYTES report_bytes=$REPORT_BYTES" >> "$LOG"
    exit 3
  fi
  sleep 10
done
set +e
wait "$TRAIN_PID"
RC=$?
set -e
printf '%s\n' "$RC" > "$ROOT/submit_logs/$RUN_ID.exit_code.txt"
trap - EXIT INT TERM
exit "$RC"
