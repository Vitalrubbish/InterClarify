#!/usr/bin/env bash
# Run one frozen external regression with bounded services and process groups.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:?}"
FREEZE="${TEXTTURN_EXTERNAL_DIR:?}"
PHASE="${TEXTTURN_EXTERNAL_PHASE:?}"
RUN_ID="${TEXTTURN_RUN_ID:?}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="$HOME/interclarify-xturnix-fleurs/envs/xturnix"
ASR_ENV="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
PY="$ENV_DIR/bin/python"
RUN="$ROOT/runs/$RUN_ID"
case "$RUN_ID" in ''|*[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
case "$PHASE" in ultrachat|fdb) ;; *) exit 2 ;; esac
[ ! -e "$RUN" ] && [ -f "$ENV_DIR/conda-meta/history" ] || exit 2
[ "$PHASE" != fdb ] || [ -f "$ASR_ENV/conda-meta/history" ] || exit 2
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || exit 2
mkdir -p "$RUN"
exec > >(tee -a "$RUN/job.log") 2>&1
SERVICE_PID='' ASR_PID='' STEP_PID='' MONITOR_PID=''
cleanup() {
 local rc=$?
 trap - EXIT INT TERM
 [ -z "$MONITOR_PID" ] || kill -TERM "$MONITOR_PID" 2>/dev/null || true
 for pid in "$STEP_PID" "$SERVICE_PID" "$ASR_PID"; do
  [ -z "$pid" ] || kill -TERM -- "-$pid" 2>/dev/null || true
 done
 sleep 2
 for pid in "$STEP_PID" "$SERVICE_PID" "$ASR_PID"; do
  [ -z "$pid" ] || kill -KILL -- "-$pid" 2>/dev/null || true
  [ -z "$pid" ] || wait "$pid" 2>/dev/null || true
 done
 printf '%s\n' "$rc" > "$RUN/exit_code.txt"
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
cp "$FREEZE/$PHASE.manifest.json" "$RUN/manifest.json"
cp "$FREEZE/candidate_identity.json" "$RUN/candidate_identity.json"
cp "$REPO/configs/textturn_external_evaluation.json" "$RUN/protocol.json"
git -C "$REPO" rev-parse HEAD > "$RUN/source_commit.txt"
"$PY" -m pip freeze > "$RUN/controller_packages.txt"
"$PY" - "$ROOT" "$REPO" "$RUN" <<'PY'
import json,sys
from pathlib import Path
repo=Path(sys.argv[2]);sys.path.insert(0,str(repo/'scripts/remote'))
from textturn_candidate import validate_candidate,read,digest
root,run=Path(sys.argv[1]),Path(sys.argv[3])
p=read(run/'protocol.json'); identity=validate_candidate(root/'runs'/p['training_run'],
 root/'dataset'/p['dataset'], repo/p['training_config'],root/'models/qwen3-0.6b')
assert identity==read(run/'candidate_identity.json')==read(run/'manifest.json')['candidate_identity']
files=[*repo.glob('scripts/remote/*textturn*'),repo/'scripts/remote/nemotron_asr_service.py',
 *repo.glob('scripts/training/*textturn*.py'),repo/'scripts/runtime/textturn_context.py',
 *repo.glob('configs/textturn*'),*list((root/'runs'/p['training_run']/'best').glob('*'))]
(run/'asset_hashes.json').write_text(json.dumps({str(f):digest(f) for f in files if f.is_file()},indent=2)+'\n')
PY
PARENT_PID=$$
(
 trap 'kill -TERM "$PARENT_PID" 2>/dev/null || true' ERR
 STARTED_SECONDS=$SECONDS
 while true; do
  GPU=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  ASSETS=$(du -sb "$ROOT/models" "$ROOT/dataset" "$ROOT/runs" | awk '{n+=$1} END {printf "%.0f\n",n}')
  REPORTS=$(du -sb "$ROOT/runs" | awk '{print $1}')
  FREE_KIB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
  printf '%s %s %s %s %s\n' "$(date -u +%FT%TZ)" "$GPU" "$ASSETS" "$REPORTS" "$FREE_KIB" >> "$RUN/resource_samples.txt"
  if [ "$GPU" -ge 22528 ] || [ "$ASSETS" -ge 10737418240 ] || [ "$REPORTS" -ge 2147483648 ] || [ "$FREE_KIB" -lt 31457280 ] || [ "$((SECONDS - STARTED_SECONDS))" -ge 7140 ]; then
   echo 'Resource stop' > "$RUN/resource_stop.txt"
   kill -TERM "$PARENT_PID"
   exit 3
  fi
  sleep 10
 done
) &
MONITOR_PID=$!
mapfile -t CANDIDATE_PATHS < <("$PY" - "$RUN/candidate_identity.json" <<'PY'
import json,sys
identity=json.load(open(sys.argv[1]))
for key in ('training','data','config'):
 print(identity[key])
PY
)
[ "${#CANDIDATE_PATHS[@]}" -eq 3 ] || exit 2
setsid "$PY" -u "$REPO/scripts/remote/textturn_controller_service.py" \
 --model "$ROOT/models/qwen3-0.6b" --data "${CANDIDATE_PATHS[1]}" \
 --training "${CANDIDATE_PATHS[0]}" --config "${CANDIDATE_PATHS[2]}" \
 --port 18816 > "$RUN/controller.log" 2>&1 &
SERVICE_PID=$!
if [ "$PHASE" = fdb ]; then
 "$ASR_ENV/bin/python" -m pip freeze > "$RUN/asr_packages.txt"
 setsid "$ASR_ENV/bin/python" -u "$REPO/scripts/remote/nemotron_asr_service.py" \
  --model "$HOME/interclarify-asr-selection/models/nemotron_en" \
  --warmup-audio "$HOME/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
  --warmup-timeout 180 --port 18815 > "$RUN/asr.log" 2>&1 &
 ASR_PID=$!
fi
run_step "$PY" - "$RUN" "$PHASE" "$REPO" <<'PY'
import json,sys,time,requests
from pathlib import Path
run,phase,repo=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
sys.path.insert(0,str(repo/'scripts/remote'));sys.path.insert(0,str(repo/'scripts/training'))
from textturn_candidate import TOKENS
from textturn_ultrachat_retest import DuplexReplayState,write_json
from build_textturn_dataset import ControlTokenizer
expected=json.loads((run/'candidate_identity.json').read_text())['adapter_sha256']
ports={18816,18815} if phase=='fdb' else {18816}
health={};deadline=time.monotonic()+300
while ports and time.monotonic()<deadline:
 for port in list(ports):
  try:
   r=requests.get(f'http://127.0.0.1:{port}/health',timeout=2);r.raise_for_status()
   if r.json()['status']=='ok':health[str(port)]=r.json();ports.remove(port)
  except requests.RequestException: pass
 if ports:time.sleep(1)
assert not ports, f'Service startup timeout: {ports}'
assert health['18816']['candidate_sha256']==expected and health['18816']['token_ids']==TOKENS
write_json(run/'health.json',health)
# These probes are interface checks outside the formal sample denominator.
case={'case_id':'interface-smoke','initial_state':'Speak','history':[], 'answers':['Hello']*2,'tail_ms':480}
tokenizer=ControlTokenizer(Path.home()/'parathink-textturn/models/qwen3-0.6b')
state=DuplexReplayState(case,tokenizer,{'control_ms':160,'assistant_tokens':3},lambda *a,**k:None)
state.snapshot_at=0.
payloads=[state.snapshot('',1)]
old=state.output_id
state.advance(2.)
assert state.state=='Listen'
state.snapshot_at=2.
payloads.append(state.snapshot('',1))
assert payloads[-1]['runtime_events'][0]['marker']=='<finish>'
assert not state.terminal('finish',2.1,old)
assert not state.snapshot('',1)['runtime_events']
responses=[]
for visible in payloads:
 r=requests.post('http://127.0.0.1:18816/decide',json=visible,timeout=10);r.raise_for_status()
 result=r.json();assert result['candidate_sha256']==expected
 assert set(result['legal_logits'])==({'keep','stop'} if visible['state']=='Speak' else {'keep','start'})
 responses.append({'visible':visible,'result':result})
write_json(run/'interface_smoke.json',responses)
PY
if [ "$PHASE" = ultrachat ]; then
 run_step "$PY" -u "$REPO/scripts/remote/textturn_ultrachat_retest.py" run \
  --manifest "$RUN/manifest.json" --tokenizer "$ROOT/models/qwen3-0.6b" \
  --control-ms 160 --output "$RUN/formal"
 run_step "$PY" - "$REPO" "$RUN" <<'PY'
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'scripts/remote'))
from textturn_external_score import score
run=Path(sys.argv[2]);score(json.loads((run/'manifest.json').read_text()),run/'formal')
PY
else
 run_step "$PY" -u "$REPO/scripts/remote/textturn_fdb_replay.py" \
  --manifest "$RUN/manifest.json" --output "$RUN/smoke" --smoke
 run_step "$PY" -u "$REPO/scripts/remote/textturn_fdb_replay.py" \
  --manifest "$RUN/manifest.json" --output "$RUN/formal"
 run_step "$PY" "$REPO/scripts/training/score_textturn_fdb.py" \
  --manifest "$RUN/manifest.json" --replay "$RUN/formal" --output "$RUN/scoring"
 run_step "$PY" - "$REPO" "$RUN" <<'PY'
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'scripts/remote'))
from textturn_external_score import score_fdb
run=Path(sys.argv[2]);score_fdb(json.loads((run/'manifest.json').read_text()),run)
PY
fi
