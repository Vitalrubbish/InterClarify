#!/usr/bin/env bash
# Submit the P1.1 asset-preparation job to the SJTU cluster.
#
# CPU-only: the job only downloads and hashes assets, so it runs on pdcpu
# without occupying a GPU (and without the GPU-utilization watchdog).
#
# Overrides: P1_IMAGE, P1_JOB_NAME, P1_CPU_PER_TASK, P1_MEM_PER_TASK_G,
#            P1_PARTITION, INTERCLARIFY_ROOT, INTERCLARIFY_ARTIFACT_ROOT.
#
# Track: vc list -j <JOBID> ; vc logs -t <TASKID>
set -euo pipefail

REPO_HPC="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
MODEL_ROOT="${INTERCLARIFY_MODEL_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
IMAGE="${P1_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2}"
JOB_NAME="${P1_JOB_NAME:-interclarify-p1-assets}"
PARTITION="${P1_PARTITION:-pdcpu}"
CPU="${P1_CPU_PER_TASK:-4}"
MEM="${P1_MEM_PER_TASK_G:-16}G"

LOG_DIR="$ARTIFACT_ROOT/p1_assets/logs_submit"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/submit.JOB.log"

echo "[submit] image=$IMAGE job=$JOB_NAME partition=$PARTITION cpu=$CPU mem=$MEM"
echo "[submit] repo=$REPO_HPC model_root=$MODEL_ROOT"

vc submit --image "$IMAGE" \
  --partition "$PARTITION" --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" \
  JOB=1:1 "$LOG_FILE" \
  --cmd "INTERCLARIFY_ROOT=$REPO_HPC INTERCLARIFY_MODEL_ROOT=$MODEL_ROOT INTERCLARIFY_ARTIFACT_ROOT=$ARTIFACT_ROOT bash $REPO_HPC/scripts/remote/run_p1_assets_node_job.sh"
