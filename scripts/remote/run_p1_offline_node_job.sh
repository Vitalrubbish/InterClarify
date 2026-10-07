#!/usr/bin/env bash
# P1.1 offline control-model sample, executed inside a cluster GPU container.
#
# Loads the fixed DuplexCascade weights from shared storage and runs the
# scripted micro-turn generation used by the official control model.  All
# assets are local, so Hugging Face/ModelScope network access is disabled.
#
# Overrides: INTERCLARIFY_ROOT, INTERCLARIFY_MODEL_ROOT,
#            INTERCLARIFY_ARTIFACT_ROOT, IC_PYTHON, IC_SCRIPT
set -uo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-/opt/interclarify}"
MODEL_ROOT="${INTERCLARIFY_MODEL_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
PYTHON="${IC_PYTHON:-/opt/conda/envs/interclarify-dev/bin/python}"

export PYTHONNOUSERSITE=True
export PYTHONPATH="$REPO_ROOT/src"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

LOG_DIR="$ARTIFACT_ROOT/p1_offline/logs_submit"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/node.$(date -u +%Y%m%dT%H%M%SZ).log"

ARGS=(
  "$REPO_ROOT/scripts/run_p1_offline_sample.py"
  --profile cluster
  --output-root "$ARTIFACT_ROOT/p1_offline"
)
if [[ -n "${IC_SCRIPT:-}" ]]; then
  ARGS+=(--script "$IC_SCRIPT")
fi

echo "[p1_offline] repo=$REPO_ROOT model_root=$MODEL_ROOT" | tee "$LOG"
"$PYTHON" "${ARGS[@]}" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "[p1_offline] run_p1_offline_sample.py rc=$RC" | tee -a "$LOG"
exit "$RC"
