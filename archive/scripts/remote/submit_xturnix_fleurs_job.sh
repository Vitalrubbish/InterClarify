#!/usr/bin/env bash
# Submit one bounded XTurnix FLEURS smoke or formal job through the cluster scheduler.
#
# The cluster wrapper rewrites the literal token "JOB" in the submitted command, so
# the in-job variables deliberately use XTURNIX_MODE / XTURNIX_RUN_ID instead.
set -euo pipefail

ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
TAG="${XTURNIX_TAG:-${XTURNIX_JOB_TAG:-}}"
MODE="${XTURNIX_MODE:-smoke}"
IMAGE="${XTURNIX_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
TIMEOUT="${XTURNIX_TIMEOUT_SECONDS:-14400}"
PARTITION="${XTURNIX_PARTITION:-pdgpu-4090}"
REPO_ROOT="${PARATHINK_ROOT:-${INTERCLARIFY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}}"

[ -n "$TAG" ] || { echo "XTURNIX_TAG is required" >&2; exit 2; }
case "$MODE" in
  smoke|formal) ;;
  *) echo "usage: XTURNIX_MODE={smoke|formal} $0" >&2; exit 2 ;;
esac

mkdir -p "$ROOT/submit_logs"
printf -v command 'XTURNIX_MODE=%q XTURNIX_RUN_ID=%q XTURNIX_ROOT=%q timeout %d bash %q' \
  "$MODE" "$TAG" "$ROOT" "$TIMEOUT" "$REPO_ROOT/scripts/remote/run_xturnix_fleurs_job.sh"
vc submit --image "$IMAGE" --partition "$PARTITION" \
  --job "xturnix-fleurs-$MODE-$TAG" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$TAG.log" --cmd "$command"
