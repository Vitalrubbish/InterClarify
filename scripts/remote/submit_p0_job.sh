#!/usr/bin/env bash
# Submit the P0 acceptance job to the SJTU cluster (pdgpu-4090).
#
# P0 does not run the models: a single GPU is requested only to prove that the
# pinned environment can see the expected accelerator.  Overrides:
#   P0_IMAGE, P0_JOB_NAME, P0_GPUS, P0_CPU_PER_GPU, P0_MEM_PER_GPU_G
#   INTERCLARIFY_ROOT, INTERCLARIFY_ARTIFACT_ROOT
#
# Usage:
#   bash scripts/remote/submit_p0_job.sh
#
# Track:
#   vc list -j <JOBID> ; vc logs -t <TASKID>
set -euo pipefail

REPO_HPC="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
IMAGE="${P0_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.1}"
JOB_NAME="${P0_JOB_NAME:-interclarify-p0-env}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
LOG_DIR="$ARTIFACT_ROOT/p0_env/logs_submit"
GPUS="${P0_GPUS:-1}"
CPU_PER_GPU="${P0_CPU_PER_GPU:-8}"
MEM_PER_GPU_G="${P0_MEM_PER_GPU_G:-32}"
CPU=$((GPUS * CPU_PER_GPU))
MEM="$((GPUS * MEM_PER_GPU_G))G"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/submit.JOB.log"

echo "[submit] image=$IMAGE job=$JOB_NAME gpus=$GPUS cpu=$CPU mem=$MEM"
echo "[submit] repo=$REPO_HPC artifact_root=$ARTIFACT_ROOT"

vc submit --image "$IMAGE" \
  --partition pdgpu-4090 --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG_FILE" \
  --cmd "INTERCLARIFY_ROOT=$REPO_HPC INTERCLARIFY_ARTIFACT_ROOT=$ARTIFACT_ROOT bash $REPO_HPC/scripts/remote/run_p0_node_job.sh"
