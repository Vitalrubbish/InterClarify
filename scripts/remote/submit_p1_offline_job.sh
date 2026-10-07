#!/usr/bin/env bash
# Submit the P1.1 offline control-model sample to the SJTU cluster.
#
# One RTX 4090 is enough for Qwen2-7B + LoRA in bf16 (the official server
# loads fp32, which would not fit 24 GB; the adapter uses bf16 without changing
# the weights).
#
# Overrides: P1_OFFLINE_IMAGE, P1_OFFLINE_JOB_NAME, P1_OFFLINE_GPUS,
#            P1_OFFLINE_CPU, P1_OFFLINE_MEM_G, INTERCLARIFY_ROOT,
#            INTERCLARIFY_MODEL_ROOT, INTERCLARIFY_ARTIFACT_ROOT.
#
# Track: vc list -j <JOBID> ; vc logs -t <TASKID>
set -euo pipefail

REPO_HPC="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
MODEL_ROOT="${INTERCLARIFY_MODEL_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
IMAGE="${P1_OFFLINE_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2}"
JOB_NAME="${P1_OFFLINE_JOB_NAME:-interclarify-p1-offline}"
GPUS="${P1_OFFLINE_GPUS:-1}"
CPU="${P1_OFFLINE_CPU:-8}"
MEM="${P1_OFFLINE_MEM_G:-64}G"

LOG_DIR="$ARTIFACT_ROOT/p1_offline/logs_submit"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/submit.JOB.log"

echo "[submit] image=$IMAGE job=$JOB_NAME gpus=$GPUS cpu=$CPU mem=$MEM"

vc submit --image "$IMAGE" \
  --partition pdgpu-4090 --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG_FILE" \
  --cmd "INTERCLARIFY_ROOT=$REPO_HPC INTERCLARIFY_MODEL_ROOT=$MODEL_ROOT INTERCLARIFY_ARTIFACT_ROOT=$ARTIFACT_ROOT bash $REPO_HPC/scripts/remote/run_p1_offline_node_job.sh"
