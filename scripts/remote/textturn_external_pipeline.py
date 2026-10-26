"""Freeze and serially submit authorized TT-011 regressions after training gates."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

from textturn_candidate import digest, read, validate_candidate

TERMINAL = {'Completed', 'Terminated', 'Canceled', 'Failed', 'Error'}


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def progress_snapshot(path):
    # Legacy writers replace progress in place; a transient partial write is not a job failure.
    try:
        return read(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def scheduler():
    result = subprocess.run(['vc', 'list', '--show-all', '--days', '3'], capture_output=True,
                            text=True, check=True, timeout=30)
    raw = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result.stdout)
    if 'Status' not in raw or 'Name' not in raw:
        raise RuntimeError('Unrecognized scheduler response')
    jobs = {}
    for line in raw.splitlines():
        fields = [v.strip() for v in line.split('|')]
        if fields[0].startswith('job-'):
            if len(fields) < 9:
                raise RuntimeError('Truncated scheduler row')
            jobs[fields[0]] = {'status': fields[3], 'description': fields[8]}
    return jobs, raw


def review_cases(manifest, review):
    result = deepcopy(manifest)
    for case in result['cases']:
        case['prefix_reviews'] = []
        for row in review['entries']:
            if row['case_id'] != case['case_id']:
                continue
            e = case['updates'][row['update_index']]
            if (e['kind'] != 'user' or e['turn'] != row['turn'] or e['text'] != row['prefix'] or
                    e['at'] != row['at'] or hashlib.sha256(e['text'].encode()).hexdigest() != row['prefix_sha256']):
                raise ValueError('Reviewed causal prefix changed')
            case['prefix_reviews'].append(row)
    return result


def prepare(root, repo, output, config_path=None):
    config_path = (config_path or repo / 'configs/textturn_external_evaluation.json').resolve()
    protocol = read(config_path)
    review = read(repo / 'configs/textturn_external_prefix_review.json')
    base = root / protocol['ultrachat_baseline']
    if digest(base) != review['baseline_manifest_sha256']:
        raise ValueError('TT-008 manifest changed since review')
    ultra = review_cases(read(base), review)
    fdb = read(root / protocol['fdb_baseline'])
    if (len(ultra['cases']) != 150 or len(ultra['sources']) != 30 or
            len(fdb['records']) != 100 or not ultra['complete'] or not fdb['complete']):
        raise ValueError('Historical planned sample identities incomplete')
    if fdb['protocol'].get('controller_state_mode') != 'action_only' or fdb['protocol']['control_ms'] != 160:
        raise ValueError('Expected original 160ms action-only FDB baseline')
    for path, expected in ultra['assets'].items():
        if digest(path) != expected:
            raise ValueError(f'UltraChat frozen asset changed: {path}')
    for case in fdb['records'] + fdb['smoke']:
        for asset in case['files'].values():
            if digest(Path(fdb['root']) / asset['path']) != asset['sha256']:
                raise ValueError('FDB frozen asset changed')
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'prepared.json', {'protocol': protocol, 'review': review,
          'ultrachat': ultra, 'fdb': fdb, 'ultrachat_baseline_sha256': digest(base),
          'fdb_baseline_sha256': digest(root / protocol['fdb_baseline']),
          'source_commit': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'],text=True).strip(),
          'protocol_path': str(config_path), 'protocol_sha256': digest(config_path),
          'review_sha256': digest(repo / 'configs/textturn_external_prefix_review.json')})


class Pipeline:
    """Persist every submission intent and receipt; never retry an ambiguous submission."""

    def __init__(self, root, repo, output):
        self.root, self.repo, self.output = root, repo, output
        self.prepared = read(output / 'prepared.json')
        self.protocol = self.prepared['protocol']
        protocol_path = Path(self.prepared.get('protocol_path', repo / 'configs/textturn_external_evaluation.json'))
        if (digest(protocol_path) != self.prepared['protocol_sha256'] or
                digest(repo / 'configs/textturn_external_prefix_review.json') != self.prepared['review_sha256']):
            raise ValueError('Prepared protocol or review changed')
        self.state_path = output / 'state.json'
        self.state = read(self.state_path) if self.state_path.exists() else {'status': 'waiting_for_training', 'jobs': {}}
        deadline = self.protocol['training_wait_deadline']
        self.deadline = datetime.fromisoformat(deadline).timestamp() if deadline is not None else None

    def save(self, status, detail=None):
        self.state.update(status=status, detail=detail, updated_at=datetime.now().astimezone().isoformat())
        write(self.state_path, self.state)
        with (self.output / 'events.jsonl').open('a') as log:
            log.write(json.dumps(self.state, ensure_ascii=False) + '\n')
        print(json.dumps(self.state, ensure_ascii=False), flush=True)

    def freeze_candidate(self):
        p = self.protocol
        train = self.root / 'runs' / p['training_run']
        data = self.root / 'dataset' / p['dataset']
        if digest(data / 'manifest.json') != p['dataset_manifest_sha256']:
            raise ValueError('Training dataset identity changed')
        if (self.root / 'submit_logs' / (p['training_run'] + '.source_commit.txt')).read_text().strip() != p['training_source_commit']:
            raise ValueError('Training source changed')
        identity = validate_candidate(train, data, self.repo / p['training_config'], self.root / 'models/qwen3-0.6b')
        frozen = self.output / 'candidate_identity.json'
        if frozen.exists():
            if read(frozen) != identity:
                raise ValueError('Frozen candidate changed')
        else:
            write(frozen, identity)
        for name, key in [('ultrachat', 'ultrachat_run'), ('fdb', 'fdb_run')]:
            manifest_path = self.output / (name + '.manifest.json')
            if manifest_path.exists():
                continue
            m = deepcopy(self.prepared[name])
            m['baseline_manifest_sha256'] = self.prepared[name + '_baseline_sha256']
            m['candidate_identity'] = identity
            m['protocol']['candidate_sha256'] = identity['adapter_sha256']
            m['protocol'].pop('cumulative_gpu_seconds', None)
            m['protocol']['maximum_job_seconds'] = 7200
            if name == 'ultrachat':
                m['protocol']['configurations'] = p['configurations']
                m['protocol']['stop_deadline_ms'] = 1000
                m['review'] = self.prepared['review']
            else:
                m['protocol']['experiment'] = p[key]
            m['protocol_sha256'] = hashlib.sha256(json.dumps(m['protocol'],sort_keys=True).encode()).hexdigest()
            write(manifest_path, m)
        return identity

    def wait_training(self):
        p = self.protocol
        while True:
            jobs, raw = scheduler()
            (self.output / 'scheduler.latest.txt').write_text(raw)
            exit_path = self.root / 'submit_logs' / (p['training_run'] + '.exit_code.txt')
            if exit_path.exists() and exit_path.read_text().strip() != '0':
                raise RuntimeError('Training failed: exit_code=' + exit_path.read_text().strip())
            job = jobs.get(p['training_job'])
            if job is None:
                raise RuntimeError('Training job missing from scheduler history')
            log = self.root / 'submit_logs' / (p['training_run'] + '.training.log')
            progress = []
            if log.exists():
                with log.open('rb') as stream:
                    stream.seek(max(0, log.stat().st_size - 2400))
                    progress = stream.read().decode(errors='replace').splitlines()[-1:]
            self.save('waiting_for_training', {'job': job, 'last_training_log': progress})
            if job['status'] in TERMINAL:
                if job['status'] != 'Completed' or not exit_path.exists() or exit_path.read_text().strip() != '0':
                    raise RuntimeError('Training terminated without successful scheduler and exit evidence')
                info = subprocess.check_output(['vc','info','--job',p['training_job']], text=True, timeout=30)
                (self.output / 'training.scheduler_info.txt').write_text(info)
                if not re.search(r'EndTime:\s*\d{4}-\d\d-\d\d', info):
                    raise RuntimeError('Training GPU release not confirmed by scheduler')
                self.freeze_candidate()
                return
            if self.deadline is not None and time.time() >= self.deadline:
                raise TimeoutError('Training wait deadline exceeded')
            time.sleep(30)

    def wait_idle(self):
        for _ in range(120):
            jobs, raw = scheduler()
            (self.output / 'scheduler.latest.txt').write_text(raw)
            active = {k:v for k,v in jobs.items() if v['status'] not in TERMINAL}
            if not active:
                return
            self.save('waiting_for_idle_scheduler', active)
            time.sleep(30)
        raise TimeoutError('Another active cluster job retained the single-job lock')

    def submit(self, phase):
        run_id = self.protocol[phase + '_run']
        existing = self.state['jobs'].get(phase)
        if existing:
            if 'job_id' not in existing:
                raise RuntimeError('Ambiguous previous submission; inspect receipt and scheduler manually')
            return existing['job_id']
        self.wait_idle()
        self.freeze_candidate()
        if (self.root / 'runs' / run_id).exists():
            raise RuntimeError('Output path already exists before submission')
        command = shlex.join(['env', 'TEXTTURN_ROOT=' + str(self.root), 'TEXTTURN_EXTERNAL_DIR=' + str(self.output),
                              'TEXTTURN_EXTERNAL_PHASE=' + phase, 'TEXTTURN_RUN_ID=' + run_id,
                              'timeout', '--signal=TERM', '--kill-after=20', '7200', 'bash',
                              str(self.repo / 'scripts/remote/run_textturn_external.sh')])
        self.state['jobs'][phase] = {'run_id': run_id, 'submission_intent': True, 'command': command}
        self.save('submitting_' + phase)
        result = subprocess.run(['vc','submit','--image',
            'docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4',
            '--partition','pdgpu-4090','--job','textturn-' + run_id,'--num-task','1',
            '--cpu-per-task','8','--mem-per-task','32G','--gpu-per-task','1','JOB=1:1',
            str(self.root / 'submit_logs' / (run_id + '.scheduler.log')), '--cmd', command],
            capture_output=True, text=True, timeout=120)
        receipt = result.stdout + result.stderr
        (self.output / (phase + '.submission.txt')).write_text(receipt)
        match = re.findall(r'job-\d+-[\w-]+', receipt)
        if result.returncode or len(set(match)) != 1:
            raise RuntimeError('Submission receipt not confirmed: ' + receipt)
        job_id = match[0]
        self.state['jobs'][phase]['job_id'] = job_id
        self.save(phase + '_submitted', receipt)
        return job_id

    def wait_job(self, phase, job_id):
        started = time.time()
        while time.time() - started < 4 * 3600:
            jobs, raw = scheduler()
            (self.output / 'scheduler.latest.txt').write_text(raw)
            job = jobs.get(job_id)
            if job is None:
                raise RuntimeError('Submitted job missing from scheduler')
            run = self.root / 'runs' / self.protocol[phase + '_run']
            progress = run / ('formal/progress.json' if phase == 'fdb' else 'formal/progress.json')
            self.save(phase + '_running' if job['status'] == 'Running' else phase + '_scheduler_wait',
                      {'scheduler': job, 'progress': progress_snapshot(progress)})
            if job['status'] in TERMINAL:
                info = subprocess.check_output(['vc','info','--job',job_id], text=True, timeout=30)
                (self.output / (phase + '.scheduler_info.txt')).write_text(info)
                rc = run / 'exit_code.txt'
                if (job['status'] != 'Completed' or not rc.exists() or rc.read_text().strip() != '0' or
                        not re.search(r'EndTime:\s*\d{4}-\d\d-\d\d', info)):
                    raise RuntimeError(phase + ' failed or GPU release unconfirmed')
                summary = read(run / ('scoring/summary.json' if phase == 'fdb' else 'formal/external_summary.json'))
                if phase == 'ultrachat' and sum(v['runtime_success'] for v in summary.values()) != 150:
                    raise RuntimeError('UltraChat runtime denominator incomplete')
                if phase == 'fdb':
                    cases = [json.loads(s) for s in (run / 'formal/cases.jsonl').read_text().splitlines()]
                    if len(cases) != 100 or not all(c['runtime_success'] for c in cases):
                        raise RuntimeError('FDB runtime denominator incomplete')
                self.save(phase + '_completed', {'job_id': job_id, 'summary': summary})
                return
            time.sleep(30)
        raise TimeoutError(phase + ' scheduler deadline exceeded')

    def run(self):
        if self.state['status'] == 'completed':
            return
        if self.state['status'] == 'stopped':
            raise RuntimeError('Pipeline stopped; original evidence requires review before restart')
        self.wait_training()
        for phase in ('ultrachat','fdb'):
            self.wait_job(phase, self.submit(phase))
        self.save('completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare','wait'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.command == 'prepare':
        prepare(args.root, repo, args.output, args.config)
    else:
        # The persistent waiter only performs bounded CPU work on the login node.
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
        with (args.root / 'submit_logs/textturn-submit.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pipeline = Pipeline(args.root, repo, args.output)
            try:
                pipeline.run()
            except Exception as exc:
                pipeline.save('stopped', repr(exc))
                raise
