#!/usr/bin/env bash
# Submit one bounded XTurnix FLEURS smoke or formal job through the cluster scheduler.
set -euo pipefail

ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
TAG="${XTURNIX_JOB_TAG:?set a unique run tag}"
MODE="${XTURNIX_JOB_MODE:-smoke}"
IMAGE="${XTURNIX_JOB_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
TIMEOUT="${XTURNIX_JOB_TIMEOUT_SECONDS:-14400}"
REPO_ROOT="${PARATHINK_ROOT:-${INTERCLARIFY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}}"

case "$MODE" in
  smoke|formal) ;;
  *) echo "usage: XTURNIX_JOB_MODE={smoke|formal} $0" >&2; exit 2 ;;
esac

mkdir -p "$ROOT/submit_logs"
printf -v command 'XTURNIX_JOB_MODE=%q XTURNIX_JOB_RUN_ID=%q XTURNIX_ROOT=%q timeout %d bash %q' \
  "$MODE" "$TAG" "$ROOT" "$TIMEOUT" "$REPO_ROOT/scripts/remote/run_xturnix_fleurs_job.sh"
vc submit --image "$IMAGE" --partition pdgpu-4090 --job "xturnix-fleurs-$MODE-$TAG" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$TAG.log" --cmd "$command"
