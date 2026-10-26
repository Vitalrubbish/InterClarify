#!/usr/bin/env bash
# Submit one frozen complete-trajectory training job after the local audit.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AUDIT="${TEXTTURN_AUDIT:-$ROOT/dataset/tt-010-fulltraj-r1/audit.json}"
case "$RUN_ID" in *[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
mkdir -p "$ROOT/submit_logs"
exec 9> "$ROOT/submit_logs/textturn-submit.lock"
flock -n 9 || exit 2
[ ! -e "$ROOT/runs/$RUN_ID" ] && [ ! -e "$ROOT/submit_logs/$RUN_ID.submission.txt" ] || exit 2
ACTIVE=$(vc list)
if printf '%s\n' "$ACTIVE" | grep -Eq 'job-[0-9]+'; then
  echo 'Another cluster job is active' >&2
  exit 2
fi
[ -f "$AUDIT" ] || exit 2
PY="$HOME/interclarify-xturnix-fleurs/envs/xturnix/bin/python"
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 30 "$PY" -c \
  'import hashlib,json,sys; from pathlib import Path; p,c,h,audit=map(Path,sys.argv[1:]); a=json.loads(audit.read_text()); digest=lambda f:hashlib.sha256(f.read_bytes()).hexdigest(); assert a["status"]=="passed" and a["manifest_sha256"]==digest(p/"manifest.json"); assert a["training_config_sha256"]==digest(c) and a["active_loss_helper_sha256"]==digest(h)' \
  "$ROOT/dataset/tt-010-fulltraj-r1" "$REPO_ROOT/configs/textturn_full_trajectory_training.json" \
  "$REPO_ROOT/scripts/training/textturn_loss.py" "$AUDIT"
printf -v command 'TEXTTURN_ROOT=%q TEXTTURN_RUN_ID=%q bash %q' \
  "$ROOT" "$RUN_ID" "$REPO_ROOT/scripts/remote/run_textturn_full_training.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition "${TEXTTURN_PARTITION:-pdgpu-4090}" --job "textturn-$RUN_ID" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$RUN_ID.scheduler.log" --cmd "$command" | tee "$ROOT/submit_logs/$RUN_ID.submission.txt"
