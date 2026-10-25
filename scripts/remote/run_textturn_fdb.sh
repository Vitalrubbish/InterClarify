#!/usr/bin/env bash
# Run real-ASR FDB smoke and 50+50 serial replays with one shared GPU allocation.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
MANIFEST="${TEXTTURN_FDB_MANIFEST:?TEXTTURN_FDB_MANIFEST is required}"
BUDGET="${TEXTTURN_FDB_BUDGET:?TEXTTURN_FDB_BUDGET is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="$HOME/interclarify-xturnix-fleurs/envs/xturnix"
ASR_ENV="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
TRAIN_DIR="$ROOT/runs/tt-002-20261025-r1"
RUN_DIR="$ROOT/runs/$RUN_ID"
case "$RUN_ID" in ''|*[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
[ ! -e "$RUN_DIR" ] || exit 2
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || exit 2
for PREFIX in "$ENV_DIR" "$ASR_ENV"; do [ -f "$PREFIX/conda-meta/history" ] || exit 2; done
mkdir -p "$RUN_DIR"
exec > >(tee -a "$RUN_DIR/job.log") 2>&1
ASR_PID='' CONTROLLER_PID='' MONITOR_PID='' STEP_PID=''
stop_services() {
  local PID
  for PID in "$ASR_PID" "$CONTROLLER_PID"; do
    [ -z "$PID" ] || kill -TERM -- "-$PID" 2>/dev/null || true
  done
  sleep 2
  for PID in "$ASR_PID" "$CONTROLLER_PID"; do
    [ -z "$PID" ] || kill -KILL -- "-$PID" 2>/dev/null || true
    [ -z "$PID" ] || wait "$PID" 2>/dev/null || true
  done
  ASR_PID='' CONTROLLER_PID=''
}
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  [ -z "$MONITOR_PID" ] || kill -TERM "$MONITOR_PID" 2>/dev/null || true
  [ -z "$STEP_PID" ] || kill -TERM -- "-$STEP_PID" 2>/dev/null || true
  stop_services
  [ -z "$STEP_PID" ] || kill -KILL -- "-$STEP_PID" 2>/dev/null || true
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
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
git -C "$REPO_ROOT" rev-parse HEAD > "$RUN_DIR/source_commit.txt"
cp "$MANIFEST" "$RUN_DIR/manifest.json"
cp "$BUDGET" "$RUN_DIR/budget.json"
"$ENV_DIR/bin/python" -m pip freeze > "$RUN_DIR/controller_packages.txt"
"$ASR_ENV/bin/python" -m pip freeze > "$RUN_DIR/asr_packages.txt"
"$ENV_DIR/bin/python" - "$REPO_ROOT" "$TRAIN_DIR" "$ROOT/models/qwen3-0.6b" "$RUN_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
repo, train, model, out = map(Path, sys.argv[1:])
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()
protocol = json.loads((repo/'configs/textturn_fdb.json').read_text())
assert digest(train/'best/adapter_model.safetensors') == protocol['candidate_sha256']
files = [*model.glob('*.json'), *model.glob('*.safetensors'), *model.glob('*.txt'),
         *repo.glob('scripts/remote/*textturn*.py'), *repo.glob('scripts/training/*textturn*.py'),
         repo/'scripts/runtime/textturn_context.py', repo/'scripts/remote/nemotron_asr_service.py',
         *repo.glob('configs/textturn*.json'), *train.glob('best/*')]
asr = Path.home()/'interclarify-asr-selection/models/nemotron_en'
files += [p for p in asr.rglob('*') if p.is_file() and '.cache' not in p.parts]
(out/'asset_hashes.json').write_text(json.dumps({str(p):digest(p) for p in files if p.is_file()}, indent=2)+'\n')
PY
PARENT_PID=$$
(
  while true; do
    GPU_MIB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
    ASSET_BYTES=$(du -sb "$ROOT/models" "$ROOT/dataset" "$ROOT/runs" | awk '{n+=$1} END {print n}')
    REPORT_BYTES=$(du -sb "$ROOT/runs" | awk '{print $1}')
    printf '%s %s %s %s\n' "$(date -u +%FT%TZ)" "$GPU_MIB" "$ASSET_BYTES" "$REPORT_BYTES" >> "$RUN_DIR/resource_samples.txt"
    if [ "$GPU_MIB" -ge 22528 ] || [ "$ASSET_BYTES" -ge 10737418240 ] || [ "$REPORT_BYTES" -ge 2147483648 ]; then
      echo 'Resource limit reached' >> "$RUN_DIR/resource_stop.txt"
      kill -TERM "$PARENT_PID"
      exit 3
    fi
    sleep 10
  done
) &
MONITOR_PID=$!
setsid "$ASR_ENV/bin/python" -u "$REPO_ROOT/scripts/remote/nemotron_asr_service.py" \
  --model "$HOME/interclarify-asr-selection/models/nemotron_en" \
  --warmup-audio "$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
  --warmup-timeout 180 --port 18815 > "$RUN_DIR/asr.log" 2>&1 &
ASR_PID=$!
setsid "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_controller_service.py" \
  --model "$ROOT/models/qwen3-0.6b" --data "$ROOT/dataset/tt-001-frozen-r3" \
  --training "$TRAIN_DIR" --config "$REPO_ROOT/configs/textturn_training.json" --port 18816 \
  > "$RUN_DIR/controller.log" 2>&1 &
CONTROLLER_PID=$!
run_step "$ENV_DIR/bin/python" - "$RUN_DIR" <<'PY'
import json, sys, time, requests
from pathlib import Path
deadline = time.monotonic() + 300
pending, health = {18815, 18816}, {}
while pending and time.monotonic() < deadline:
    for port in list(pending):
        try:
            result = requests.get(f'http://127.0.0.1:{port}/health', timeout=2)
            result.raise_for_status()
            if result.json()['status'] == 'ok':
                health[str(port)] = result.json(); pending.remove(port)
        except requests.RequestException: pass
    if pending: time.sleep(1)
assert not pending, f'Services not ready: {pending}'
Path(sys.argv[1], 'health.json').write_text(json.dumps(health, indent=2)+'\n')
PY
run_step "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_fdb_replay.py" \
  --manifest "$MANIFEST" --tokenizer "$ROOT/models/qwen3-0.6b" --output "$RUN_DIR/smoke" --smoke
run_step "$ENV_DIR/bin/python" -u "$REPO_ROOT/scripts/remote/textturn_fdb_replay.py" \
  --manifest "$MANIFEST" --tokenizer "$ROOT/models/qwen3-0.6b" --output "$RUN_DIR/formal"
stop_services
run_step "$ENV_DIR/bin/python" "$REPO_ROOT/scripts/training/score_textturn_fdb.py" \
  --manifest "$MANIFEST" --replay "$RUN_DIR/formal" --output "$RUN_DIR/scoring"
