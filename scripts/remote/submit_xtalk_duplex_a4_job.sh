#!/usr/bin/env bash
# Submit the Stage A4 DuplexCascade acceptance job to pdgpu-4090.
set -euo pipefail

TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
IMAGE="${DUPLEX_A4_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.3}"
JOB_NAME="${DUPLEX_A4_JOB_NAME:-xtalk-duplex-a4}"
GPUS="${DUPLEX_A4_GPUS:-3}"
CPU="${DUPLEX_A4_CPU:-24}"
MEM="${DUPLEX_A4_MEM:-96G}"
LOG_ROOT="${DUPLEX_A4_SUBMIT_LOG_ROOT:-$TASK_ROOT/data/runs/submit_logs}"
mkdir -p "$LOG_ROOT"
LOG="$LOG_ROOT/submit.$(date -u +%Y%m%dT%H%M%SZ).log"

printf -v NODE_COMMAND 'INTERCLARIFY_DUPLEX_ROOT=%q CONDA_SH=%q ' "$TASK_ROOT" "/opt/conda/etc/profile.d/conda.sh"
for variable in $(compgen -e); do
  case "$variable" in
    DUPLEX_*|XTALK_ROUND1_ROOT|XTALK_ROUND1_MODEL_ROOT|XTALK_MOSS_SERVICE_ROOT|XTALK_MOSS_SOURCE_ROOT)
      printf -v assignment '%s=%q ' "$variable" "${!variable}"
      NODE_COMMAND+="$assignment"
      ;;
  esac
done
printf -v NODE_SCRIPT '%q' "$TASK_ROOT/scripts/remote/run_xtalk_duplex_a4_node_job.sh"
NODE_COMMAND+="bash $NODE_SCRIPT"

vc submit --image "$IMAGE" \
  --partition pdgpu-4090 --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG" \
  --cmd "$NODE_COMMAND"
