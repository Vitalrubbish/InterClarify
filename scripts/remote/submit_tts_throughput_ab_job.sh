#!/usr/bin/env bash
# Submit the MOSS-TTS throughput A/B job (single 4090) to pdgpu-4090.
#
# The job measures the T1 (local-transformer compile/CUDA graph) and T2 (sampling
# head) arms of `scripts/remote/moss_tts_patch.py` against the unpatched upstream
# path, then writes reports/tts_throughput/<tag>/tts_throughput.{md,json}.
set -euo pipefail

TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
IMAGE="${DUPLEX_A4_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.3}"
JOB_NAME="${TTS_AB_JOB_NAME:-xtalk-tts-throughput}"
GPUS="${TTS_AB_GPUS:-1}"
CPU="${TTS_AB_CPU:-8}"
MEM="${TTS_AB_MEM:-32G}"
# A10 is a fallback for a saturated 4090 queue: it is slower, so only the
# relative speedup between arms is comparable across different partitions.
PARTITION="${TTS_AB_PARTITION:-pdgpu-4090}"
LOG_ROOT="${DUPLEX_A4_SUBMIT_LOG_ROOT:-$TASK_ROOT/data/runs/submit_logs}"
mkdir -p "$LOG_ROOT"
LOG="$LOG_ROOT/submit.tts_throughput.$(date -u +%Y%m%dT%H%M%SZ).log"

printf -v NODE_COMMAND 'INTERCLARIFY_ROOT=%q CONDA_SH=%q ' "$TASK_ROOT" "/opt/conda/etc/profile.d/conda.sh"
for variable in $(compgen -e); do
  # Never forward a name ending in JOB_NAME: `vc` rewrites the literal token
  # JOB_NAME inside the node command, which would turn `X_JOB_NAME=...` into a
  # bogus `X_=...` assignment and abort the job before it starts.
  case "$variable" in
    *JOB_NAME) continue ;;
  esac
  case "$variable" in
    XTALK_*|TTS_AB_*|RUN_TAG|MOSS_ENV|CLIENT_ENV|TTS_PORT)
      printf -v assignment '%s=%q ' "$variable" "${!variable}"
      NODE_COMMAND+="$assignment"
      ;;
  esac
done
printf -v NODE_SCRIPT '%q' "$TASK_ROOT/scripts/remote/run_tts_throughput_ab_node_job.sh"
NODE_COMMAND+="bash $NODE_SCRIPT"

vc submit --image "$IMAGE" \
  --partition "$PARTITION" --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG" \
  --cmd "$NODE_COMMAND"
