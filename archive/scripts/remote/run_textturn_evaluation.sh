#!/usr/bin/env bash
# Evaluate one development-selected TextTurn candidate without changing any model.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
TRAIN_ID="${TEXTTURN_TRAIN_ID:?TEXTTURN_TRAIN_ID is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="$HOME/interclarify-xturnix-fleurs/envs/xturnix"
ASR_ENV="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
TTS_ENV="$HOME/interclarify-english-integration-20261018-v1/envs/tts"
RUN_DIR="$ROOT/runs/$RUN_ID"
TRAIN_DIR="$ROOT/runs/$TRAIN_ID"
DATA="$ROOT/dataset/tt-001-frozen-r3"
MODEL="$ROOT/models/qwen3-0.6b"
CONFIG="$REPO_ROOT/configs/textturn_training.json"
ASR_PID='' CONTROLLER_PID='' MONITOR_PID='' STEP_PID=''
case "$RUN_ID:$TRAIN_ID" in *[!A-Za-z0-9._:-]*|.*) exit 2 ;; esac
[ ! -e "$RUN_DIR" ] || { echo 'Evaluation run already exists' >&2; exit 2; }
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || exit 2
for PREFIX in "$ENV_DIR" "$ASR_ENV" "$TTS_ENV"; do
  [ -f "$PREFIX/conda-meta/history" ] || { echo 'Missing conda metadata' >&2; exit 2; }
done
mkdir -p "$RUN_DIR"
exec > >(tee -a "$RUN_DIR/job.log") 2>&1
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  [ -z "$MONITOR_PID" ] || kill -TERM "$MONITOR_PID" 2>/dev/null || true
  for PID in "$STEP_PID" "$ASR_PID" "$CONTROLLER_PID"; do
    [ -z "$PID" ] || kill -TERM -- "-$PID" 2>/dev/null || true
  done
  sleep 2
  for PID in "$STEP_PID" "$ASR_PID" "$CONTROLLER_PID"; do
    [ -z "$PID" ] || kill -KILL -- "-$PID" 2>/dev/null || true
    [ -z "$PID" ] || wait "$PID" 2>/dev/null || true
  done
  printf '%s\n' "$rc" > "$RUN_DIR/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_step() {
  setsid "$@" <&0 &
  STEP_PID=$!
  wait "$STEP_PID"
  STEP_PID=''
}
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
git -C "$REPO_ROOT" rev-parse HEAD > "$RUN_DIR/source_commit.txt"
"$ENV_DIR/bin/python" -m pip freeze > "$RUN_DIR/packages.txt"
"$ENV_DIR/bin/python" - "$TRAIN_DIR/candidate.json" <<'PY'
import json, sys
candidate=json.load(open(sys.argv[1]))
assert candidate['continue_online'], 'Development gate did not permit evaluation'
assert candidate['elapsed_seconds'] <= 4 * 3600, 'Training exceeded its job budget'
PY
PARENT_PID=$$
(
  while true; do
    GPU_MIB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
    ASSET_BYTES=$(du -sb "$ROOT/models" "$ROOT/dataset" "$ROOT/runs" | awk '{n+=$1} END {print n}')
    REPORT_BYTES=$(du -sb "$ROOT/runs" | awk '{print $1}')
    printf '%s %s %s %s\n' "$(date -u +%FT%TZ)" "$GPU_MIB" "$ASSET_BYTES" "$REPORT_BYTES" >> "$RUN_DIR/resource_samples.txt"
    if [ "$GPU_MIB" -ge 22528 ] || [ "$ASSET_BYTES" -ge 10737418240 ] || [ "$REPORT_BYTES" -ge 2147483648 ]; then
      kill -TERM "$PARENT_PID"
      exit 3
    fi
    sleep 10
  done
) &
MONITOR_PID=$!
echo 'Running fixed independent text evaluation'
run_step "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_evaluate.py" \
  --model "$MODEL" --data "$DATA" --training "$TRAIN_DIR" --config "$CONFIG" --output "$RUN_DIR/independent-text"
echo 'Preparing traceable synthetic test speech'
run_step "$TTS_ENV/bin/python" -u "$REPO_ROOT/scripts/remote/prepare_textturn_audio.py" \
  --data "$DATA" --snapshot "${TEXTTURN_TTS_MODEL:?TEXTTURN_TTS_MODEL is required}" \
  --output "$ROOT/dataset/$RUN_ID-audio"
echo 'Starting isolated real ASR and shadow controller services'
setsid "$ASR_ENV/bin/python" -u "$REPO_ROOT/scripts/remote/nemotron_asr_service.py" \
  --model "$HOME/interclarify-asr-selection/models/nemotron_en" \
  --warmup-audio "$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
  --warmup-timeout 180 --port 18815 > "$RUN_DIR/asr.log" 2>&1 &
ASR_PID=$!
setsid "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_controller_service.py" \
  --model "$MODEL" --data "$DATA" --training "$TRAIN_DIR" --config "$CONFIG" --port 18816 \
  > "$RUN_DIR/controller.log" 2>&1 &
CONTROLLER_PID=$!
run_step "$ENV_DIR/bin/python" - <<'PY'
import time, requests
deadline=time.monotonic()+300
pending={18815,18816}
while pending and time.monotonic()<deadline:
    for port in list(pending):
        try:
            response=requests.get(f'http://127.0.0.1:{port}/health',timeout=2)
            response.raise_for_status()
            if response.json()['status']=='ok':pending.remove(port)
        except requests.RequestException:pass
    if pending:time.sleep(1)
assert not pending, f'Services did not become ready: {pending}'
PY
run_step "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_shadow_replay.py" \
  --audio "$ROOT/dataset/$RUN_ID-audio" --tokenizer "$MODEL" --output "$RUN_DIR/shadow-smoke" --limit 3
"$ENV_DIR/bin/python" - "$RUN_DIR/shadow-smoke/summary.json" <<'PY'
import json,sys
result=json.load(open(sys.argv[1]))
assert result['runtime']['rate']==1. and result['context']['rate']==1., 'Real interface smoke failed'
PY
echo 'Running frozen 300-source speech evaluation'
run_step "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_shadow_replay.py" \
  --audio "$ROOT/dataset/$RUN_ID-audio" --tokenizer "$MODEL" --output "$RUN_DIR/shadow-formal"
"$ENV_DIR/bin/python" - "$RUN_DIR" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); summary=json.loads((root/'shadow-formal/summary.json').read_text())
(root/'README.md').write_text('# TT-004 语音影子评估\n\n结论：'+summary['conclusion']+
    '。完整分母、95%区间及逐例失败见shadow-formal。输入为固定Kokoro合成语音，'
    '仅模拟生成与播放生命周期，不等同真实人类或扬声器播放验收。文本结果另见independent-text。\n')
PY
