#!/usr/bin/env bash
set -euo pipefail
ROOT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-issue001-word-20261019
KYUTAI=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-kyutai
OUTPUT="$ROOT/data/word-capture-r1"
[ ! -e "$OUTPUT" ] || exit 2
cd "$ROOT"
sha256sum -c source.sha256 > "$ROOT/capture-source-check.txt"
VENV="$KYUTAI/repos/moshi/rust/moshi-server/.venv"
for libdir in "$VENV"/lib/python3.12/site-packages/nvidia/*/lib; do
  [ -d "$libdir" ] && LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
done
LD_LIBRARY_PATH="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="$KYUTAI/lib:$LD_LIBRARY_PATH"
setsid "$KYUTAI/bin/bin/moshi-server" worker --config "$KYUTAI/configs/config-stt-en_fr-hf.local.toml" --port 31627 > "$ROOT/word-capture-server.log" 2>&1 &
SERVER=$!
cleanup() {
  local rc=$?
  trap - EXIT
  kill -TERM -- "-$SERVER" 2>/dev/null || true
  wait "$SERVER" 2>/dev/null || true
  printf '%s\n' "$rc" > "$ROOT/word-capture-exit.txt"
  exit "$rc"
}
trap cleanup EXIT
for attempt in $(seq 1 180); do
  kill -0 "$SERVER"
  if curl -s -m 1 http://127.0.0.1:31627/ >/dev/null; then break; fi
  sleep 1
done
/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev/bin/python -u scripts/remote/capture_kyutai_words.py \
  --url ws://127.0.0.1:31627/api/asr-streaming \
  --manifest /hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/runs/endpoint-b4d12d6/manifest.json \
  --server-binary "$KYUTAI/bin/bin/moshi-server" \
  --server-config "$KYUTAI/configs/config-stt-en_fr-hf.local.toml" --output "$OUTPUT" > "$ROOT/word-capture-client.log" 2>&1
