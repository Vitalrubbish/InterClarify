#!/usr/bin/env bash
# Submit a round-one X-Talk acceptance job to the SJTU cluster (pdgpu-4090).
#
# Usage:
#   bash scripts/remote/submit_xtalk_round1_job.sh asr
#   bash scripts/remote/submit_xtalk_round1_job.sh services
#   bash scripts/remote/submit_xtalk_round1_job.sh chain
#
# Modes:
#   asr       1 GPU  /  8 CPU /  32G   -- three ASR chunk-window smokes
#   services  4 GPU / 32 CPU / 128G   -- llm + turn_detector + tts verification
#   chain     4 GPU / 32 CPU / 128G   -- full path ASR -> LLM -> TTS
#
# Track:
#   vc list -j <JOBID> ; vc logs -t <TASKID>
#
# Overrides:
#   XTALK_ROUND1_IMAGE, XTALK_JOB_NAME, INTERCLARIFY_ROOT,
#   XTALK_ASR_GPUS / XTALK_SERVICES_GPUS (GPU counts per mode)
set -euo pipefail

MODE="${1:?usage: submit_xtalk_round1_job.sh [asr|services]}"

REPO_HPC="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
IMAGE="${XTALK_ROUND1_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.2}"
JOB_NAME="${XTALK_JOB_NAME:-xtalk-round1-$MODE}"
ARTIFACT_ROOT="${XTALK_ROUND1_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/artifacts}"
LOG_DIR="$ARTIFACT_ROOT/submit_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/submit.$MODE.$(date -u +%Y%m%dT%H%M%SZ).log"

case "$MODE" in
  asr)      GPUS="${XTALK_ASR_GPUS:-1}";      CPU=8;  MEM=32G ;;
  services) GPUS="${XTALK_SERVICES_GPUS:-4}"; CPU=32; MEM=128G ;;
  chain)    GPUS="${XTALK_CHAIN_GPUS:-4}";    CPU=32; MEM=128G ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac

echo "[submit] mode=$MODE image=$IMAGE job=$JOB_NAME gpus=$GPUS cpu=$CPU mem=$MEM"
echo "[submit] repo=$REPO_HPC"

vc submit --image "$IMAGE" \
  --partition pdgpu-4090 --job "$JOB_NAME" --num-task 1 \
  --cpu-per-task "$CPU" --mem-per-task "$MEM" --gpu-per-task "$GPUS" \
  JOB=1:1 "$LOG_FILE" \
  --cmd "INTERCLARIFY_ROOT=$REPO_HPC CONDA_SH=/opt/conda/etc/profile.d/conda.sh bash $REPO_HPC/scripts/remote/run_xtalk_round1_node_job.sh $MODE"
