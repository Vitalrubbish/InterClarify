#!/usr/bin/env bash
# P1.2 real-time duplex link, executed inside a cluster GPU container.
#
# The job requests two GPUs: GPU 0 runs the official DuplexCascade control
# model (bf16, ~17 GB), GPU 1 runs the pinned Kyutai STT/TTS services (started
# here from shared storage if not already reachable).  Scenario audio is
# synthesized through the TTS service, then the continuous scripted scenarios
# run headlessly with a virtual playback sink.
#
# Assets (built once, see docs/jobs/p1_2_live_link.md):
#   P1.1 models : $INTERCLARIFY_MODEL_ROOT/modelscope/...
#   Kyutai stack: /hpc_stor03/sjtu_home/xuan.zhang/interclarify-kyutai/
#
# Overrides: INTERCLARIFY_ROOT, INTERCLARIFY_MODEL_ROOT,
#            INTERCLARIFY_ARTIFACT_ROOT, IC_PYTHON, KYUTAI_ROOT,
#            IC_STT_GPU, IC_TTS_GPU
set -uo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-/opt/interclarify}"
MODEL_ROOT="${INTERCLARIFY_MODEL_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
KYUTAI_ROOT="${KYUTAI_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-kyutai}"
PYTHON="${IC_PYTHON:-/opt/conda/envs/interclarify-dev/bin/python}"

export PYTHONNOUSERSITE=True
export PYTHONPATH="$REPO_ROOT/src"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

LOG_DIR="$ARTIFACT_ROOT/p1_2_live/logs_submit"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/node.$(date -u +%Y%m%dT%H%M%SZ).log"

# -- step 0: Kyutai STT/TTS services on GPU 1 --------------------------------
if ! bash "$REPO_ROOT/scripts/remote/start_kyutai_services.sh" "${IC_STT_GPU:-1}" "${IC_TTS_GPU:-1}" 2>&1 | tee -a "$LOG"; then
  echo "[p1_2_live] ERROR: Kyutai services failed to start (see $KYUTAI_ROOT/logs)" | tee -a "$LOG"
  exit 3
fi

# -- step 1: synthesize scripted scenario audio via the TTS service ----------
echo "[p1_2_live] synthesizing scenario audio" | tee -a "$LOG"
"$PYTHON" "$REPO_ROOT/scripts/prepare_p1_2_scenarios.py" \
  --profile cluster 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
if [[ "$RC" != "0" ]]; then
  echo "[p1_2_live] prepare_p1_2_scenarios.py rc=$RC" | tee -a "$LOG"
  exit "$RC"
fi

# -- step 2: continuous scripted scenarios over the full duplex link ---------
echo "[p1_2_live] running live-link scenarios" | tee -a "$LOG"
"$PYTHON" "$REPO_ROOT/scripts/run_p1_2_live_link.py" \
  --profile cluster \
  --output-root "$ARTIFACT_ROOT/p1_2_live" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "[p1_2_live] run_p1_2_live_link.py rc=$RC" | tee -a "$LOG"
exit "$RC"
