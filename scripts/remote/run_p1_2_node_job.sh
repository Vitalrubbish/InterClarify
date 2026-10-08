#!/usr/bin/env bash
# P1.2 real-time duplex link, executed inside a cluster GPU container.
#
# Prerequisites (see docs/jobs/p1_2_live_link.md):
#   1. the Kyutai STT/TTS moshi-server instances must be reachable at the
#      configured endpoints (ports 31607/31608 on 127.0.0.1 of this node);
#   2. P1.1 assets (DuplexCascade snapshot + base model) on shared storage.
#
# Steps: synthesize the scripted scenario audio through the TTS service, then
# launch the unmodified official control-model server (bf16, local weights)
# and run the continuous scripted scenarios headlessly (virtual playback sink).
#
# Overrides: INTERCLARIFY_ROOT, INTERCLARIFY_MODEL_ROOT,
#            INTERCLARIFY_ARTIFACT_ROOT, IC_PYTHON
set -uo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-/opt/interclarify}"
MODEL_ROOT="${INTERCLARIFY_MODEL_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models}"
ARTIFACT_ROOT="${INTERCLARIFY_ARTIFACT_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts}"
PYTHON="${IC_PYTHON:-/opt/conda/envs/interclarify-dev/bin/python}"

export PYTHONNOUSERSITE=True
export PYTHONPATH="$REPO_ROOT/src"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

LOG_DIR="$ARTIFACT_ROOT/p1_2_live/logs_submit"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/node.$(date -u +%Y%m%dT%H%M%SZ).log"

# -- prerequisite probe: Kyutai STT/TTS services -----------------------------
probe() {
  "$PYTHON" - "$1" <<'PY'
import socket, sys
host, port = sys.argv[1].rsplit(":", 1)
try:
    with socket.create_connection((host, int(port)), timeout=3):
        sys.exit(0)
except OSError as exc:
    print(f"unreachable: {exc}")
    sys.exit(1)
PY
}

STT_ENDPOINT="${IC_STT_ENDPOINT:-127.0.0.1:31607}"
TTS_ENDPOINT="${IC_TTS_ENDPOINT:-127.0.0.1:31608}"
for endpoint in "$STT_ENDPOINT" "$TTS_ENDPOINT"; do
  if ! probe "$endpoint"; then
    echo "[p1_2_live] ERROR: Kyutai service at $endpoint not reachable." | tee "$LOG"
    echo "[p1_2_live] Deploy moshi-server first, see docs/jobs/p1_2_live_link.md (前置条件)." | tee -a "$LOG"
    exit 3
  fi
done
echo "[p1_2_live] STT/TTS endpoints reachable: $STT_ENDPOINT $TTS_ENDPOINT" | tee "$LOG"

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
