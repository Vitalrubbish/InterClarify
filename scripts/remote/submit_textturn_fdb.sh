#!/usr/bin/env bash
# Audit actual scheduler allocations and submit one bounded, serial FDB job.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
MANIFEST="${TEXTTURN_FDB_MANIFEST:?TEXTTURN_FDB_MANIFEST is required}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$HOME/miniconda3/envs/interclarify-x2-turn-data/bin/python"
case "$RUN_ID" in ''|*[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
mkdir -p "$ROOT/submit_logs"
exec 9> "$ROOT/submit_logs/textturn-submit.lock"
flock -n 9 || exit 2
[ ! -e "$ROOT/runs/$RUN_ID" ] && [ ! -e "$ROOT/submit_logs/$RUN_ID.budget.json" ] || exit 2
[ -f "$(dirname "$(dirname "$PY")")/conda-meta/history" ] || exit 2
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
BUDGET="$ROOT/submit_logs/$RUN_ID.budget.json"
timeout 90 "$PY" - "$BUDGET" "$MANIFEST" "$REPO_ROOT/configs/textturn_fdb.json" "$ROOT/runs/tt-002-20261025-r1" <<'PY'
from datetime import datetime
import hashlib, json, re, subprocess, sys
from pathlib import Path
def vc(*args):
    result = subprocess.check_output(['vc', *args], text=True, timeout=25)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result)
active = vc('list')
assert not re.search(r'job-\d+', active), 'Another cluster job is active'
raw = vc('list', '--show-all', '--days', '3')
jobs = []
for line in raw.splitlines():
    fields = [p.strip() for p in line.split('|')]
    if len(fields) < 9 or not fields[0].startswith('job-') or not fields[8].startswith('textturn-'):
        continue
    assert fields[3] in ('Completed', 'Terminated', 'Canceled', 'Failed', 'Error'), 'Unfinished TextTurn job'
    info = vc('info', '--job', fields[0])
    start = re.search(r'StartTime:\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)', info)
    end = re.search(r'EndTime:\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)', info)
    assert start and end, 'Missing actual scheduler allocation times'
    duration = (datetime.fromisoformat(end[1]) - datetime.fromisoformat(start[1])).total_seconds()
    assert duration >= 0
    jobs.append({'job_id': fields[0], 'start': start[1], 'end': end[1], 'gpu': int(fields[6]),
                 'gpu_seconds': duration*int(fields[6]), 'scheduler_info': info})
assert {'job-179286310634760697957-xuan-zhang', 'job-179287011405618549973-xuan-zhang'} <= {j['job_id'] for j in jobs}
protocol = json.loads(Path(sys.argv[3]).read_text())
assert re.fullmatch('[0-9a-f]{64}', protocol['candidate_sha256']), 'Invalid SHA256 format'
training = Path(sys.argv[4])
candidate = json.loads((training/'candidate.json').read_text())
with (training/'best/adapter_model.safetensors').open('rb') as stream:
    sha = hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b''): sha.update(block)
assert sha.hexdigest() == candidate['adapter_sha256'] == protocol['candidate_sha256'], 'Frozen candidate mismatch before allocation'
manifest = json.loads(Path(sys.argv[2]).read_text())
assert manifest['complete'] and len(manifest['records']) == 100
assert manifest['protocol_sha256'] == hashlib.sha256(Path(sys.argv[3]).read_bytes()).hexdigest()
remaining = protocol['cumulative_gpu_seconds'] - sum(j['gpu_seconds'] for j in jobs)
limit = int(min(protocol['maximum_job_seconds'], remaining - 60))
assert limit > 0, 'No remaining cumulative GPU budget'
Path(sys.argv[1]).write_text(json.dumps({'jobs': jobs, 'scheduler_history': raw,
    'used_gpu_seconds': sum(j['gpu_seconds'] for j in jobs), 'remaining_gpu_seconds': remaining,
    'job_limit_seconds': limit, 'cleanup_reserve_seconds': 60}, indent=2)+'\n')
print(limit)
PY
LIMIT=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["job_limit_seconds"])' "$BUDGET")
printf -v command 'TEXTTURN_ROOT=%q TEXTTURN_RUN_ID=%q TEXTTURN_FDB_MANIFEST=%q TEXTTURN_FDB_BUDGET=%q timeout --signal=TERM --kill-after=30 %q bash %q' \
  "$ROOT" "$RUN_ID" "$MANIFEST" "$BUDGET" "$LIMIT" "$REPO_ROOT/scripts/remote/run_textturn_fdb.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition "${TEXTTURN_PARTITION:-pdgpu-4090}" --job "textturn-$RUN_ID" \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$ROOT/submit_logs/$RUN_ID.scheduler.log" --cmd "$command" | tee "$ROOT/submit_logs/$RUN_ID.submission.txt"
