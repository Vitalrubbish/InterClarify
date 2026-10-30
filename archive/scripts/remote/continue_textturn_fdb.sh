#!/usr/bin/env bash
# Wait for one fixed predecessor and submit the authorized serial comparison.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
PREDECESSOR="${TEXTTURN_PREDECESSOR_RUN:?TEXTTURN_PREDECESSOR_RUN is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$HOME/miniconda3/envs/interclarify-x2-turn-data/bin/python"
case "$RUN_ID:$PREDECESSOR" in *[!A-Za-z0-9._:-]*|.*) exit 2 ;; esac
mkdir -p "$ROOT/submit_logs"
exec 8> "$ROOT/submit_logs/$RUN_ID.pipeline.lock"
flock -n 8 || exit 2
STATUS="$ROOT/submit_logs/$RUN_ID.pipeline.json"
[ ! -e "$STATUS" ] || { echo 'Continuation already recorded' >&2; exit 2; }
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
state() {
  "$PY" - "$STATUS" "$1" "${2:-}" <<'PY'
import json, sys, time
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'status':sys.argv[2], 'detail':sys.argv[3],
    'updated_unix':time.time()}, indent=2)+'\n')
PY
}
state waiting_for_predecessor "$PREDECESSOR"
DEADLINE=$((SECONDS + 7800))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
  EXIT_FILE="$ROOT/runs/$PREDECESSOR/exit_code.txt"
  if [ -f "$EXIT_FILE" ]; then
    RC=$(cat "$EXIT_FILE")
    if [ "$RC" != 0 ]; then
      state stopped_predecessor_failed "exit_code=$RC"
      exit 1
    fi
    ACTIVE=$(timeout 30 vc list | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' | awk '/job-[0-9]/ {n++} END {print n+0}')
    if [ "$ACTIVE" -eq 0 ]; then
      state submitting_after_budget_audit "$PREDECESSOR"
      if RESULT=$(bash "$REPO_ROOT/scripts/remote/submit_textturn_fdb.sh" 2>&1); then
        printf '%s\n' "$RESULT"
        state submitted "$RESULT"
        exit 0
      fi
      printf '%s\n' "$RESULT" >&2
      state stopped_submission_or_budget "$RESULT"
      exit 1
    fi
  fi
  sleep 15
done
state stopped_predecessor_deadline "$PREDECESSOR"
exit 1
