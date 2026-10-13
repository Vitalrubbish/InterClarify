#!/usr/bin/env bash
# Submit the DuplexCascade marker probe to pdgpu-4090 (single GPU, text only).
set -euo pipefail

TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
IMAGE="${DUPLEX_PROBE_IMAGE:-${DUPLEX_A4_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.3}}"
JOB_NAME="${DUPLEX_PROBE_JOB_NAME:-xtalk-duplex-marker-probe}"
GPUS="${DUPLEX_PROBE_GPUS:-1}"
CPU="${DUPLEX_PROBE_CPU:-8}"
MEM="${DUPLEX_PROBE_MEM:-32G}"
LOG_ROOT="${DUPLEX_PROBE_SUBMIT_LOG_ROOT:-$TASK_ROOT/data/runs/submit_logs}"
mkdir -p "$LOG_ROOT"
LOG="$LOG_ROOT/submit.probe.$(date -u +%Y%m%dT%H%M%SZ).log"

printf -v NODE_COMMAND 'INTERCLARIFY_DUPLEX_ROOT=%q CONDA_SH=%q ' "$TASK_ROOT" "/opt/conda/etc/profile.d/conda.sh"
for variable in $(compgen -e); do
  case "$variable" in
    DUPLEX_*|XTALK_ROUND1_ROOT|XTALK_ROUND1_MODEL_ROOT)
      printf -v assignment '%s=%q ' "$variable" "${!variable}"
      NODE_COMMAND+="$assignment"
      ;;
  esac
done
printf -v NODE_SCRIPT '%q' "$TASK_ROOT/scripts/remote/run_duplex_probe_node_job.sh"
NODE_COMMAND+="bash $NODE_SCRIPT"

vc submit --image "$IMAGE" \
  --partition pdgpu-4090 --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG" \
  --cmd "$NODE_COMMAND"
