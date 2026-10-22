#!/usr/bin/env bash
# Submit one X2Q-014 evaluation stage to the scheduler.
#
# smoke  : dev warm-up plus the fixed five test inputs, for protocol, clock,
#          format and resource checks only.
# formal : dev warm-up plus all 100 frozen test inputs, then both scorers.
#
# The script only submits; it does not wait, retry or add GPUs.  Submission is
# not evidence of success.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
SOURCE="${X2_TURN_SOURCE:?set the frozen InterClarify source checkout}"
JOB_SCRIPT="${X2_TURN_JOB_SCRIPT:?set the job script path}"
STAGE="${X2_TURN_STAGE:?set smoke or formal}"
TAG="${X2_TURN_TAG:?set a unique run tag}"
RUN_ID="${X2_TURN_RUN_ID:?set a unique replay run id}"
SOURCE_COMMIT="${X2_TURN_SOURCE_COMMIT:-$(git -C "$SOURCE" rev-parse HEAD)}"
IMAGE="${X2_TURN_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
GPU_PARTITION="${X2_TURN_GPU_PARTITION:-pdgpu-4090}"
TIMEOUT="${X2_TURN_TIMEOUT:-14400}"

case "$STAGE" in smoke|formal) ;; *) echo "Unsupported stage: $STAGE" >&2; exit 2 ;; esac

mkdir -p "$ROOT/logs" "$ROOT/runs"
LOG="$ROOT/logs/$TAG-$STAGE.log"
[ ! -e "$LOG" ] || { echo "Submit log already exists: $LOG" >&2; exit 2; }

OUTPUT="$ROOT/runs/job-$TAG-$STAGE"
[ ! -e "$OUTPUT" ] || { echo "Job output already exists: $OUTPUT" >&2; exit 2; }
[ ! -e "$ROOT/runs/$RUN_ID" ] || { echo "Replay run already exists: $RUN_ID" >&2; exit 2; }
[ ! -e "$ROOT/runs/dev-$TAG" ] || { echo "Dev run already exists: dev-$TAG" >&2; exit 2; }

printf -v COMMAND \
  'X2_TURN_ROOT=%q X2_TURN_SOURCE=%q X2_TURN_STAGE=%q X2_TURN_TAG=%q X2_TURN_RUN_ID=%q X2_TURN_DEV_RUN_ID=%q X2_TURN_OUTPUT=%q X2_TURN_SOURCE_COMMIT=%q timeout %q bash %q' \
  "$ROOT" "$SOURCE" "$STAGE" "$TAG" "$RUN_ID" "dev-$TAG" "$OUTPUT" \
  "$SOURCE_COMMIT" "$TIMEOUT" "$JOB_SCRIPT"

vc submit --image "$IMAGE" --partition "$GPU_PARTITION" --job "x2q014-$STAGE-$TAG" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$LOG" --cmd "$COMMAND"
