#!/usr/bin/env bash
# Submit independent Nemotron and Kokoro integration verification jobs.
set -euo pipefail
ROOT="${ENGLISH_COMPONENT_ROOT:?set frozen experiment root}"
TAG="${ENGLISH_COMPONENT_TAG:?set unique run tag}"
IMAGE="${ENGLISH_COMPONENT_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
mkdir -p "$ROOT/submit_logs"
for backend in asr tts; do
  printf -v command 'ENGLISH_COMPONENT_ROOT=%q ENGLISH_COMPONENT_BACKEND=%q ENGLISH_COMPONENT_OUTPUT=%q timeout 1800 bash %q' \
    "$ROOT" "$backend" "$ROOT/data/runs/$TAG-$backend" "$ROOT/scripts/remote/run_english_component_job.sh"
  vc submit --image "$IMAGE" --partition pdgpu-4090 --job "english-$backend-$TAG" \
    --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
    JOB=1:1 "$ROOT/submit_logs/$TAG-$backend.log" --cmd "$command"
done
