#!/usr/bin/env bash
# Submit one X2-Turn deployment stage to the scheduler.
#
# setup  : CPU job that builds the isolated conda environment, installs the
#          pinned vLLM wheel plus overlay.
# model  : CPU job that downloads, verifies and exports the pinned checkpoint.
# deploy : single-GPU job that starts the service and runs the protocol probe.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
SOURCE="${X2_TURN_SOURCE:?set the frozen InterClarify source checkout}"
STAGE="${X2_TURN_STAGE:?set setup, model or deploy}"
TAG="${X2_TURN_TAG:?set a unique run tag}"
SOURCE_COMMIT="${X2_TURN_SOURCE_COMMIT:-$(git -C "$SOURCE" rev-parse HEAD)}"
IMAGE="${X2_TURN_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
GPU_PARTITION="${X2_TURN_GPU_PARTITION:-pdgpu-4090}"
SETUP_TIMEOUT="${X2_TURN_SETUP_TIMEOUT:-14400}"
MODEL_TIMEOUT="${X2_TURN_MODEL_TIMEOUT:-14400}"
DEPLOY_TIMEOUT="${X2_TURN_DEPLOY_TIMEOUT:-14400}"
ENV_PREFIX="${X2_TURN_CONDA_ENV:-$HOME/miniconda3/envs/interclarify-x2-turn-vllm}"

mkdir -p "$ROOT/logs" "$ROOT/runs"
LOG="$ROOT/logs/$TAG-$STAGE.log"
[ ! -e "$LOG" ] || { echo "Submit log already exists: $LOG" >&2; exit 2; }

case "$STAGE" in
  setup)
    OUTPUT="$ROOT/runs/$TAG/setup"
    BUNDLE_SHA="${X2_TURN_SOURCE_BUNDLE_SHA256:?set the source bundle sha256 transferred to the remote}"
    printf -v COMMAND 'X2_TURN_ROOT=%q X2_TURN_SETUP_OUTPUT=%q X2_TURN_SOURCE_BUNDLE_SHA256=%q timeout %q bash %q' \
      "$ROOT" "$OUTPUT" "$BUNDLE_SHA" "$SETUP_TIMEOUT" "$SOURCE/scripts/remote/setup_x2_turn_vllm_env.sh"
    vc submit --image "$IMAGE" --partition pdcpu --job "x2-setup-$TAG" \
      --num-task 1 --cpu-per-task 4 --mem-per-task 16G --gpu-per-task 0 \
      JOB=1:1 "$LOG" --cmd "$COMMAND"
    ;;
  model)
    printf -v COMMAND 'X2_TURN_ROOT=%q HF_ENDPOINT=%q timeout %q %q --root %q prepare' \
      "$ROOT" "${HF_ENDPOINT:-https://hf-mirror.com}" "$MODEL_TIMEOUT" \
      "$ENV_PREFIX/bin/python" "$SOURCE/scripts/remote/prepare_x2_turn_model.py" "$ROOT"
    vc submit --image "$IMAGE" --partition pdcpu --job "x2-model-$TAG" \
      --num-task 1 --cpu-per-task 4 --mem-per-task 16G --gpu-per-task 0 \
      JOB=1:1 "$LOG" --cmd "$COMMAND"
    ;;
  deploy)
    OUTPUT="$ROOT/runs/$TAG/deploy"
    printf -v COMMAND 'X2_TURN_ROOT=%q X2_TURN_OUTPUT=%q X2_TURN_STAGE=deploy X2_TURN_SOURCE=%q X2_TURN_SOURCE_COMMIT=%q X2_TURN_SMOKE_AUDIO=%q timeout %q bash %q' \
      "$ROOT" "$OUTPUT" "$SOURCE" "$SOURCE_COMMIT" "${X2_TURN_SMOKE_AUDIO:-}" \
      "$DEPLOY_TIMEOUT" "$SOURCE/scripts/remote/run_x2_turn_complete_job.sh"
    vc submit --image "$IMAGE" --partition "$GPU_PARTITION" --job "x2-deploy-$TAG" \
      --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
      JOB=1:1 "$LOG" --cmd "$COMMAND"
    ;;
  *)
    echo "Unsupported stage: $STAGE" >&2
    exit 2
    ;;
esac
