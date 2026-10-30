#!/usr/bin/env bash
# Run the two frozen prefix configurations serially within one allocation.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?}"
MANIFEST="${TEXTTURN_RETEST_MANIFEST:?}"
BUDGET="${TEXTTURN_RETEST_BUDGET:?}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="$HOME/interclarify-xturnix-fleurs/envs/xturnix"
PY="$ENV_DIR/bin/python"
RUN="$ROOT/runs/$RUN_ID"
case "$RUN_ID" in ''|*[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
[ -f "$ENV_DIR/conda-meta/history" ] || exit 2
[ ! -e "$RUN" ] || exit 2
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || exit 2
mkdir -p "$RUN"
exec > >(tee -a "$RUN/job.log") 2>&1
SERVICE_PID='' STEP_PID='' MONITOR_PID=''
cleanup() {
 local rc=$?
 trap - EXIT INT TERM
 [ -z "$MONITOR_PID" ] || kill -TERM "$MONITOR_PID" 2>/dev/null || true
 for pid in "$STEP_PID" "$SERVICE_PID"; do
  [ -z "$pid" ] || kill -TERM -- "-$pid" 2>/dev/null || true
 done
 sleep 2
 for pid in "$STEP_PID" "$SERVICE_PID"; do
  [ -z "$pid" ] || kill -KILL -- "-$pid" 2>/dev/null || true
  [ -z "$pid" ] || wait "$pid" 2>/dev/null || true
 done
 printf '%s\n' "$rc" > "$RUN/exit_code.txt"
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
cp "$MANIFEST" "$RUN/manifest.json"
cp "$BUDGET" "$RUN/budget.json"
git -C "$REPO" rev-parse HEAD > "$RUN/source_commit.txt"
"$PY" -m pip freeze > "$RUN/packages.txt"
run_step "$PY" - "$ROOT" "$REPO" "$RUN" <<'PY'
import hashlib,json,sys
from pathlib import Path
root,repo,out=map(Path,sys.argv[1:])
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
m=json.loads((out/'manifest.json').read_text()); budget=json.loads((out/'budget.json').read_text())
assert digest(out/'manifest.json')==budget['manifest_sha256']
assert digest(root/'runs/tt-002-20261025-r1/best/adapter_model.safetensors')==m['protocol']['candidate_sha256']
files=[*repo.glob('scripts/remote/*textturn*'),*repo.glob('scripts/training/*textturn*.py'),
 *repo.glob('configs/textturn*.json'),*root.glob('models/qwen3-0.6b/*'),
 *root.glob('runs/tt-002-20261025-r1/best/*')]
(out/'asset_hashes.json').write_text(json.dumps({str(p):digest(p) for p in files if p.is_file()},indent=2)+'\n')
PY
PARENT_PID=$$
(
 while true; do
  GPU=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  ASSETS=$(du -sb "$ROOT/models" "$ROOT/dataset" "$ROOT/runs" | awk '{n+=$1} END {printf "%.0f\n",n}')
  REPORTS=$(du -sb "$ROOT/runs" | awk '{print $1}')
  FREE=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
  printf '%s %s %s %s %s\n' "$(date -u +%FT%TZ)" "$GPU" "$ASSETS" "$REPORTS" "$FREE" >> "$RUN/resource_samples.txt"
  if [ "$GPU" -ge 22528 ] || [ "$ASSETS" -ge 10737418240 ] || [ "$REPORTS" -ge 2147483648 ] || [ "$FREE" -lt 31457280 ]; then
   echo 'Resource limit reached' > "$RUN/resource_stop.txt"
   kill -TERM "$PARENT_PID"
   exit 3
  fi
  sleep 10
 done
) &
MONITOR_PID=$!
setsid "$PY" -u "$REPO/scripts/remote/textturn_controller_service.py" \
 --model "$ROOT/models/qwen3-0.6b" --data "$ROOT/dataset/tt-001-frozen-r3" \
 --training "$ROOT/runs/tt-002-20261025-r1" --config "$REPO/configs/textturn_training.json" \
 --port 18816 > "$RUN/controller.log" 2>&1 &
SERVICE_PID=$!
run_step "$PY" - "$RUN" <<'PY'
import json,sys,time,requests
from pathlib import Path
deadline=time.monotonic()+300
while time.monotonic()<deadline:
 try:
  r=requests.get('http://127.0.0.1:18816/health',timeout=2);r.raise_for_status()
  if r.json()['status']=='ok':
   Path(sys.argv[1],'health.json').write_text(json.dumps(r.json())+'\n')
   break
 except requests.RequestException: pass
 time.sleep(1)
else: raise RuntimeError('Controller startup timed out')
PY
for PERIOD in 480 160; do
 echo "Starting frozen retest: $PERIOD ms"
 run_step "$PY" -u "$REPO/scripts/remote/textturn_ultrachat_retest.py" run \
  --manifest "$MANIFEST" --tokenizer "$ROOT/models/qwen3-0.6b" \
  --control-ms "$PERIOD" --output "$RUN/period-$PERIOD"
done
