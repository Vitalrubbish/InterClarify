#!/usr/bin/env bash
# Submit one bounded TextTurn training job through the cluster scheduler.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$RUN_ID" in *[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
mkdir -p "$ROOT/submit_logs"
printf -v command 'TEXTTURN_ROOT=%q TEXTTURN_RUN_ID=%q timeout 14400 bash %q' \
  "$ROOT" "$RUN_ID" "$REPO_ROOT/scripts/remote/run_textturn_training.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition "${TEXTTURN_PARTITION:-pdgpu-4090}" --job "textturn-$RUN_ID" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$RUN_ID.scheduler.log" --cmd "$command"
