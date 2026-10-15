#!/usr/bin/env bash
# Submit the ASR streaming-contract comparison (single GPU, no service) to pdgpu-4090.
#
# The job compares the released decoder's unfixed chunk window (our 0 vs the
# official 2) and both exposure conventions (raw text vs committed prefix) on a
# balanced sample of the FDB v1.0 corpus, then writes
# reports/asr_contract/<tag>/asr_contract.{md,json}.
set -euo pipefail

TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
IMAGE="${DUPLEX_A4_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}"
JOB_NAME="${ASR_AB_JOB_NAME:-xtalk-asr-contract}"
GPUS="${ASR_AB_GPUS:-1}"
CPU="${ASR_AB_CPU:-8}"
MEM="${ASR_AB_MEM:-32G}"
PARTITION="${ASR_AB_PARTITION:-pdgpu-4090}"
LOG_ROOT="${DUPLEX_A4_SUBMIT_LOG_ROOT:-$TASK_ROOT/data/runs/submit_logs}"
mkdir -p "$LOG_ROOT"
LOG="$LOG_ROOT/submit.asr_contract.$(date -u +%Y%m%dT%H%M%SZ).log"

printf -v NODE_COMMAND 'INTERCLARIFY_ROOT=%q CONDA_SH=%q ' "$TASK_ROOT" "/opt/conda/etc/profile.d/conda.sh"
for variable in $(compgen -e); do
  # Never forward a name ending in JOB_NAME: `vc` rewrites the literal token
  # JOB_NAME inside the node command, which would turn `X_JOB_NAME=...` into a
  # bogus `X_=...` assignment and abort the job before it starts.
  case "$variable" in
    *JOB_NAME) continue ;;
  esac
  case "$variable" in
    XTALK_*|ASR_AB_*|RUN_TAG|ASR_ENV|CLIENT_ENV)
      printf -v assignment '%s=%q ' "$variable" "${!variable}"
      NODE_COMMAND+="$assignment"
      ;;
  esac
done
printf -v NODE_SCRIPT '%q' "$TASK_ROOT/scripts/remote/run_asr_contract_ab_node_job.sh"
NODE_COMMAND+="bash $NODE_SCRIPT"

vc submit --image "$IMAGE" \
  --partition "$PARTITION" --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG" \
  --cmd "$NODE_COMMAND"
