#!/usr/bin/env bash
# Run the XTurnix pause-token diagnostic probe on one scheduler GPU.
# This is not the frozen XTX-005/006 replay; it never loads Nemotron.
set -euo pipefail

RUN_ID="${XTURNIX_PROBE_RUN_ID:-}"
SOURCE_RUN="${XTURNIX_PROBE_SOURCE_RUN:-xtx-005-smoke-20261023-a10-r4}"
ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
REPO_ROOT="${PARATHINK_ROOT:-${INTERCLARIFY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}}"
ENV_DIR="${XTURNIX_ENV_DIR:-$ROOT/envs/xturnix}"
ENV_PY="$ENV_DIR/bin/python"
CONFIG="$REPO_ROOT/configs/xturnix_fleurs_test.json"
MODEL="$ROOT/models/xturnix-pt"
OUT="$ROOT/runs/$RUN_ID"

[ -n "$RUN_ID" ] || { echo "XTURNIX_PROBE_RUN_ID is required" >&2; exit 2; }
case "$RUN_ID" in
  *[!A-Za-z0-9._-]*|.*) echo "invalid probe run id: $RUN_ID" >&2; exit 2 ;;
esac
[ -x "$ENV_PY" ] || { echo "missing XTurnix environment: $ENV_PY" >&2; exit 2; }
[ -f "$CONFIG" ] || { echo "missing config: $CONFIG" >&2; exit 2; }
[ -f "$MODEL/turn_pipeline.py" ] || { echo "missing model: $MODEL" >&2; exit 2; }
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  echo "probe output already exists: $OUT" >&2
  exit 2
fi
mkdir -p "$OUT"
exec > >(tee -a "$OUT/probe.log") 2>&1
trap 'rc=$?; printf "%s\n" "$rc" > "$OUT/exit_code.txt"; exit "$rc"' EXIT

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8

printf 'run_id=%s source_run=%s root=%s source=%s\n' \
  "$RUN_ID" "$SOURCE_RUN" "$ROOT" "$REPO_ROOT"
nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total \
  --format=csv > "$OUT/gpu.csv"

"$ENV_PY" -u "$REPO_ROOT/scripts/remote/xturnix_pause_probe.py" \
  --root "$ROOT" --source-run "$SOURCE_RUN" --output "$OUT" \
  --model "$MODEL" --config "$CONFIG"
