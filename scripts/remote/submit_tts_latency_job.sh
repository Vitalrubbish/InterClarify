#!/usr/bin/env bash
# Submit the component baseline to one 4090, without touching existing jobs.
set -euo pipefail
TASK_ROOT="${TTS_TASK_ROOT:?set independent checkout}"
OUTPUT="${TTS_OUTPUT:?set new output directory}"
[[ "$TASK_ROOT" = /* && "$OUTPUT" = /* ]] || { echo 'Absolute paths required' >&2; exit 2; }
LOG_ROOT="$(dirname "$OUTPUT")/submit_logs"
mkdir -p "$LOG_ROOT"
printf -v NODE_COMMAND 'TTS_TASK_ROOT=%q TTS_OUTPUT=%q ' "$TASK_ROOT" "$OUTPUT"
for variable in TTS_ONLY_ARMS TTS_CODEC_LOAD_THREADS TTS_HEALTH_TIMEOUT TTS_STACK_DIAGNOSTIC TTS_BATCH_FRAMES TTS_EARLY_COMPILE TTS_REFERENCE TTS_PORT TTS_CLIENT_ENV TTS_MOSS_ENV XTALK_ROUND1_ROOT XTALK_ROUND1_MODEL_ROOT XTALK_MOSS_SERVICE_ROOT XTALK_MOSS_SOURCE_ROOT; do
  if [[ -v "$variable" ]]; then
    printf -v assignment '%s=%q ' "$variable" "${!variable}"
    NODE_COMMAND+="$assignment"
  fi
done
NODE_FILE=run_tts_latency_node_job.sh
DESCRIPTION=tts-latency-baseline
if [[ "${TTS_SCREEN_JOB:-0}" = 1 ]]; then
  NODE_FILE=run_tts_latency_screen_job.sh
  DESCRIPTION=tts-latency-screen
fi
printf -v NODE_SCRIPT '%q' "$TASK_ROOT/scripts/remote/$NODE_FILE"
NODE_COMMAND+="bash $NODE_SCRIPT"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-4090 --job "$DESCRIPTION" --num-task 1 \
  --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$LOG_ROOT/$(basename "$OUTPUT").log" --cmd "$NODE_COMMAND"
