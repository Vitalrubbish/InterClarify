#!/usr/bin/env bash
# Freeze actual cumulative allocation before submitting one serial retest job.
set -euo pipefail
ROOT="${TEXTTURN_ROOT:-$HOME/parathink-textturn}"
RUN_ID="${TEXTTURN_RUN_ID:?TEXTTURN_RUN_ID is required}"
MANIFEST="${TEXTTURN_RETEST_MANIFEST:?TEXTTURN_RETEST_MANIFEST is required}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$HOME/miniconda3/envs/interclarify-x2-turn-data/bin/python"
case "$RUN_ID" in ''|*[!A-Za-z0-9._-]*|.*) exit 2 ;; esac
mkdir -p "$ROOT/submit_logs"
exec 9> "$ROOT/submit_logs/textturn-submit.lock"
flock -n 9 || exit 2
BUDGET="$ROOT/submit_logs/$RUN_ID.budget.json"
[ ! -e "$ROOT/runs/$RUN_ID" ] && [ ! -e "$BUDGET" ] || exit 2
[ -f "$(dirname "$(dirname "$PY")")/conda-meta/history" ] || exit 2
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
LIMIT=$(timeout 120 "$PY" - "$MANIFEST" "$BUDGET" "$ROOT" <<'PY'
from datetime import datetime
import hashlib,json,re,subprocess,sys
from pathlib import Path
manifest,budget,root=map(Path,sys.argv[1:])
m=json.loads(manifest.read_text()); p=m['protocol']
def vc(*args):
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', subprocess.check_output(['vc',*args],text=True,timeout=25))
assert not re.search(r'job-\d+',vc('list')), 'Another cluster job is active'
raw=vc('list','--show-all','--days','3'); jobs=[]
for line in raw.splitlines():
    fields=[f.strip() for f in line.split('|')]
    if len(fields)<9 or not fields[0].startswith('job-') or not fields[8].startswith('textturn-'): continue
    assert fields[3] in ('Completed','Terminated','Canceled','Failed','Error')
    info=vc('info','--job',fields[0])
    start=re.search(r'StartTime:\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)',info)
    end=re.search(r'EndTime:\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)',info)
    assert start and end, 'Missing scheduler times'
    seconds=(datetime.fromisoformat(end[1])-datetime.fromisoformat(start[1])).total_seconds()*int(fields[6])
    assert seconds>=0
    jobs.append({'job_id':fields[0],'gpu_seconds':seconds,'scheduler_info':info})
assert {'job-179286310634760697957-xuan-zhang','job-179287011405618549973-xuan-zhang',
        'job-179291166384532199286-xuan-zhang'} <= {j['job_id'] for j in jobs}
used=sum(j['gpu_seconds'] for j in jobs)
assert used>=21251, 'Scheduler history lost previously allocated jobs'
remaining=p['cumulative_gpu_seconds']-used
limit=int(min(p['maximum_job_seconds'],remaining-p['cleanup_reserve_seconds']))
assert limit>300, 'Insufficient shared budget even for startup'
assert m['complete'] and len(m['sources'])==p['source_limit']
assert hashlib.sha256((root/'runs/tt-002-20261025-r1/best/adapter_model.safetensors').read_bytes()).hexdigest()==p['candidate_sha256']
assert not budget.exists()
budget.write_text(json.dumps({'jobs':jobs,'scheduler_history':raw,'used_gpu_seconds':used,
 'remaining_gpu_seconds':remaining,'job_limit_seconds':limit,'cleanup_reserve_seconds':p['cleanup_reserve_seconds'],
 'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()},indent=2)+'\n')
print(limit)
PY
)
printf -v COMMAND 'TEXTTURN_ROOT=%q TEXTTURN_RUN_ID=%q TEXTTURN_RETEST_MANIFEST=%q TEXTTURN_RETEST_BUDGET=%q timeout --signal=TERM --kill-after=30 %q bash %q' \
 "$ROOT" "$RUN_ID" "$MANIFEST" "$BUDGET" "$LIMIT" "$REPO/scripts/remote/run_textturn_ultrachat.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
 --partition "${TEXTTURN_PARTITION:-pdgpu-4090}" --job "textturn-$RUN_ID" \
 --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
 JOB=1:1 "$ROOT/submit_logs/$RUN_ID.scheduler.log" --cmd "$COMMAND" | tee "$ROOT/submit_logs/$RUN_ID.submission.txt"
