#!/usr/bin/env bash
# Continue one authorized training run into a single, serial evaluation job.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
TRAIN_ID="${TEXTTURN_TRAIN_ID:?TEXTTURN_TRAIN_ID is required}"
EVAL_ID="${TEXTTURN_EVAL_ID:?TEXTTURN_EVAL_ID is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$HOME/miniconda3/envs/interclarify-x2-turn-data/bin/python"
TTS_MODEL="$HOME/interclarify-tts-selection-20261018/models/hf/hub/models--hexgrad--Kokoro-82M/snapshots/f3ff3571791e39611d31c381e3a41a3af07b4987"
STATUS="$ROOT/submit_logs/$EVAL_ID.pipeline.json"
case "$TRAIN_ID:$EVAL_ID" in *[!A-Za-z0-9._:-]*|.*) exit 2 ;; esac
state() {
  "$PY" - "$STATUS" "$1" "${2:-}" <<'PY'
import json,sys,time
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'status':sys.argv[2], 'detail':sys.argv[3],
                                       'updated_unix':time.time()},indent=2)+'\n')
PY
}
state waiting_for_training "$TRAIN_ID"
DEADLINE=$((SECONDS + 15300))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
  EXIT_FILE="$ROOT/submit_logs/$TRAIN_ID.exit_code.txt"
  if [ -f "$EXIT_FILE" ]; then
    RC=$(cat "$EXIT_FILE")
    if [ "$RC" != 0 ]; then
      state stopped_training_failed "exit_code=$RC"
      exit 1
    fi
    break
  fi
  sleep 30
done
if [ ! -f "$ROOT/submit_logs/$TRAIN_ID.exit_code.txt" ]; then
  state stopped_training_deadline 'Training did not publish a successful exit code before the deadline'
  exit 1
fi
if [ ! -f "$ROOT/runs/$TRAIN_ID/candidate.json" ]; then
  state stopped_missing_candidate 'Training did not deliver a frozen candidate before the deadline'
  exit 1
fi
if ! "$PY" - "$ROOT/runs/$TRAIN_ID/candidate.json" <<'PY'
import json,sys
candidate=json.load(open(sys.argv[1]))
assert candidate['continue_online'], 'Development gate rejected continuation'
assert candidate['elapsed_seconds'] + 14400 <= 28800, 'Cumulative GPU budget would be exceeded'
PY
then
  state stopped_development_gate 'No full candidate approved by development results'
  exit 0
fi
# Wait for the completed training container to release its allocated GPU.
for ATTEMPT in $(seq 1 20); do
  ACTIVE=$(vc list | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' | awk '/job-[0-9]/ {n++} END {print n+0}')
  [ "$ACTIVE" -ne 0 ] || break
  sleep 15
done
if [ "$ACTIVE" -ne 0 ]; then
  state stopped_active_job 'Another cluster job is active; single-job bound retained'
  exit 1
fi
printf -v command 'TEXTTURN_ROOT=%q TEXTTURN_TRAIN_ID=%q TEXTTURN_RUN_ID=%q TEXTTURN_TTS_MODEL=%q timeout --signal=TERM --kill-after=30 14400 bash %q' \
  "$ROOT" "$TRAIN_ID" "$EVAL_ID" "$TTS_MODEL" "$REPO_ROOT/scripts/remote/run_textturn_evaluation.sh"
if ! RESULT=$(vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-4090 --job "textturn-$EVAL_ID" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$EVAL_ID.scheduler.log" --cmd "$command" 2>&1); then
  state stopped_submission_failed "$RESULT"
  exit 1
fi
printf '%s\n' "$RESULT"
state evaluation_submitted "$RESULT"
