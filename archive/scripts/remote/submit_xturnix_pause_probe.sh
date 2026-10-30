#!/usr/bin/env bash
# Submit the XTurnix pause-token diagnostic probe to the scheduler.
set -euo pipefail

ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
TAG="${XTURNIX_PROBE_TAG:?set a unique probe tag}"
SOURCE_RUN="${XTURNIX_PROBE_SOURCE_RUN:-xtx-005-smoke-20261023-a10-r4}"
IMAGE="${XTURNIX_PROBE_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
TIMEOUT="${XTURNIX_PROBE_TIMEOUT_SECONDS:-1800}"
PARTITION="${XTURNIX_PROBE_PARTITION:-pdgpu-a10}"
REPO_ROOT="${PARATHINK_ROOT:-${INTERCLARIFY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}}"

mkdir -p "$ROOT/submit_logs"
printf -v command 'XTURNIX_PROBE_RUN_ID=%q XTURNIX_PROBE_SOURCE_RUN=%q XTURNIX_ROOT=%q timeout %d bash %q' \
  "$TAG" "$SOURCE_RUN" "$ROOT" "$TIMEOUT" \
  "$REPO_ROOT/scripts/remote/run_xturnix_pause_probe.sh"
vc submit --image "$IMAGE" --partition "$PARTITION" \
  --job "xturnix-pause-probe-$TAG" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$TAG.log" --cmd "$command"
