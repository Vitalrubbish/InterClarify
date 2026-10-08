#!/usr/bin/env bash
# Start the pinned Kyutai STT/TTS services for P1.2 (idempotent).
#
# The services live on shared storage (built once, see
# docs/3rd-party/KyutaiServices.md and docs/jobs/p1_2_live_link.md):
#   binary : $KYUTAI_ROOT/bin/bin/moshi-server  (moshi-server 0.6.4, cuda)
#   configs: $KYUTAI_ROOT/configs/*.local.toml  (local model paths)
# This wrapper is used by run_p1_2_node_job.sh inside GPU containers and can
# also be run manually on any node that sees the shared storage.
#
# Usage: start_kyutai_services.sh [stt_gpu=1] [tts_gpu=1]
# Env:   KYUTAI_ROOT (default below), IC_STT_PORT=31607, IC_TTS_PORT=31608
set -uo pipefail

KYUTAI_ROOT="${KYUTAI_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-kyutai}"
STT_GPU="${1:-1}"
TTS_GPU="${2:-1}"
STT_PORT="${IC_STT_PORT:-31607}"
TTS_PORT="${IC_TTS_PORT:-31608}"
READY_TIMEOUT_S="${IC_KYUTAI_READY_TIMEOUT_S:-600}"

probe() {
  # TCP probe via bash's /dev/tcp (no python dependency)
  local host="${1%:*}" port="${1##*:}"
  (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null
}

wait_ready() {
  local name="$1" endpoint="$2" deadline=$((SECONDS + READY_TIMEOUT_S))
  while (( SECONDS < deadline )); do
    if probe "$endpoint"; then
      echo "[kyutai] $name ready at $endpoint"
      return 0
    fi
    sleep 2
  done
  echo "[kyutai] ERROR: $name not ready at $endpoint within ${READY_TIMEOUT_S}s"
  return 1
}

if probe "127.0.0.1:$STT_PORT"; then
  echo "[kyutai] STT already running on $STT_PORT"
else
  bash "$KYUTAI_ROOT/run/start_stt.sh" "$STT_GPU" "$STT_PORT"
fi
if probe "127.0.0.1:$TTS_PORT"; then
  echo "[kyutai] TTS already running on $TTS_PORT"
else
  bash "$KYUTAI_ROOT/run/start_tts.sh" "$TTS_GPU" "$TTS_PORT"
fi

wait_ready "STT" "127.0.0.1:$STT_PORT" || exit 1
wait_ready "TTS" "127.0.0.1:$TTS_PORT" || exit 1
