#!/usr/bin/env bash
# Submit one finite pilot job after validating the new frozen data audit.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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
PY="$HOME/interclarify-xturnix-fleurs/envs/xturnix/bin/python"
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 120 "$PY" -c \
 'import hashlib,json,sys;from pathlib import Path;p=Path(sys.argv[1]);repo=Path(sys.argv[2]);a=json.loads((p/"audit.json").read_text());m=p/"manifest.json";assert a["status"]=="passed" and a["manifest_sha256"]==hashlib.sha256(m.read_bytes()).hexdigest();assert json.loads(m.read_text())["training_allowed"];assert a["training_config_sha256"]==hashlib.sha256((repo/"configs/textturn_repair_pilot.json").read_bytes()).hexdigest();assert a["loss_helper_sha256"]==hashlib.sha256((repo/"scripts/training/textturn_loss.py").read_bytes()).hexdigest()' \
 "$ROOT/dataset/tt-010-repair-20261027-r5" "$REPO_ROOT"
[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ] || { echo 'Frozen source must be clean' >&2; exit 2; }
printf -v command 'TEXTTURN_ROOT=%q TEXTTURN_RUN_ID=%q bash %q' "$ROOT" "$RUN_ID" "$REPO_ROOT/scripts/remote/run_textturn_repair_pilot.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-a10 --job "textturn-$RUN_ID" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$RUN_ID.scheduler.log" --cmd "$command" | tee "$ROOT/submit_logs/$RUN_ID.submission.txt"
