#!/usr/bin/env bash
# P0 acceptance job executed inside the cluster container.
#
# Writes all evidence to shared storage so it is visible from the dev machine:
#   $ARTIFACT_DIR/
#     environment.txt          # check_env.py report (status + hashes of versions)
#     env.json                 # machine-readable env report
#     audio_io.json            # audio device probe (headless => no devices)
#     smoke/                   # two identical replay runs (structure consistency)
#     nvidia-smi.txt
#     git.txt
#     run.log
#
# Requires the image built from scripts/remote/Dockerfile.p0 (env at
# /opt/conda/envs/interclarify-dev).  Config/env overrides:
#   INTERCLARIFY_ROOT, INTERCLARIFY_ARTIFACT_ROOT, IC_RUN_TAG
set -uo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-/opt/interclarify}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
TAG="${IC_RUN_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
ARTIFACT_DIR="$ARTIFACT_ROOT/p0_env/$TAG"
PYTHON="${IC_PYTHON:-/opt/conda/envs/interclarify-dev/bin/python}"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONNOUSERSITE=True
export PYTHONPATH="$REPO_ROOT/src"

mkdir -p "$ARTIFACT_DIR"

{
  echo "[run_p0_node_job] tag=$TAG"
  echo "[run_p0_node_job] repo=$REPO_ROOT"
  echo "[run_p0_node_job] artifact_dir=$ARTIFACT_DIR"
  echo "[run_p0_node_job] python=$PYTHON"
} | tee "$ARTIFACT_DIR/run.log"

nvidia-smi > "$ARTIFACT_DIR/nvidia-smi.txt" 2>&1 || true
{ git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null; git -C "$REPO_ROOT" status --porcelain 2>/dev/null; } > "$ARTIFACT_DIR/git.txt" 2>&1 || true

echo "[run_p0_node_job] environment check (require GPU)" | tee -a "$ARTIFACT_DIR/run.log"
"$PYTHON" "$REPO_ROOT/scripts/check_env.py" \
  --require-gpu \
  --out "$ARTIFACT_DIR/environment.txt" \
  --json-out "$ARTIFACT_DIR/env.json" | tee -a "$ARTIFACT_DIR/run.log"
ENV_RC=${PIPESTATUS[0]}

echo "[run_p0_node_job] audio I/O probe" | tee -a "$ARTIFACT_DIR/run.log"
"$PYTHON" "$REPO_ROOT/scripts/check_audio_io.py" \
  --json-out "$ARTIFACT_DIR/audio_io.json" | tee -a "$ARTIFACT_DIR/run.log" || true

echo "[run_p0_node_job] two identical replay smoke runs" | tee -a "$ARTIFACT_DIR/run.log"
"$PYTHON" "$REPO_ROOT/scripts/run_p0_smoke.py" --profile cluster \
  --output-root "$ARTIFACT_DIR/smoke" --run-id p0-smoke-a | tee -a "$ARTIFACT_DIR/run.log"
"$PYTHON" "$REPO_ROOT/scripts/run_p0_smoke.py" --profile cluster \
  --output-root "$ARTIFACT_DIR/smoke" --run-id p0-smoke-b | tee -a "$ARTIFACT_DIR/run.log"

echo "[run_p0_node_job] evidence written to $ARTIFACT_DIR" | tee -a "$ARTIFACT_DIR/run.log"
exit "$ENV_RC"
