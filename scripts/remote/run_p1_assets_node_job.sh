#!/usr/bin/env bash
# P1.1 DuplexCascade asset preparation, executed inside a cluster container.
#
# Downloads and verifies the pinned official source, the gated DuplexCascade
# weights and the base LLM into shared storage.  The Hugging Face token is read
# from a gitignored file (or HF_TOKEN) and never placed on the command line.
#
# Overrides:
#   INTERCLARIFY_ROOT, INTERCLARIFY_MODEL_ROOT, INTERCLARIFY_ARTIFACT_ROOT,
#   IC_HF_TOKEN_FILE, IC_PYTHON, HF_ENDPOINT
set -uo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-/opt/interclarify}"
MODEL_ROOT="${INTERCLARIFY_MODEL_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
TOKEN_FILE="${IC_HF_TOKEN_FILE:-$REPO_ROOT/hf_token.txt}"
PYTHON="${IC_PYTHON:-/opt/conda/envs/interclarify-dev/bin/python}"
PROVIDER="${IC_ASSET_PROVIDER:-modelscope}"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONNOUSERSITE=True

# The gated Hugging Face path needs a token; the ModelScope mirror does not.
if [[ "$PROVIDER" == "huggingface" && -z "${HF_TOKEN:-}" && -f "$TOKEN_FILE" ]]; then
  HF_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  export HF_TOKEN
fi
if [[ "$PROVIDER" == "huggingface" && -z "${HF_TOKEN:-}" ]]; then
  echo "[p1_assets] no Hugging Face token: set HF_TOKEN or place it in $TOKEN_FILE" >&2
  exit 2
fi

LOG_DIR="$ARTIFACT_ROOT/p1_assets/logs_submit"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/node.$(date -u +%Y%m%dT%H%M%SZ).log"

echo "[p1_assets] repo=$REPO_ROOT model_root=$MODEL_ROOT" | tee "$LOG"
echo "[p1_assets] provider=$PROVIDER hf_endpoint=$HF_ENDPOINT python=$PYTHON" | tee -a "$LOG"

"$PYTHON" "$REPO_ROOT/scripts/remote/prepare_p1_assets.py" \
  --repo-root "$REPO_ROOT" \
  --model-root "$MODEL_ROOT" \
  --artifact-root "$ARTIFACT_ROOT" \
  --provider "$PROVIDER" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "[p1_assets] prepare_p1_assets.py rc=$RC" | tee -a "$LOG"
exit "$RC"
