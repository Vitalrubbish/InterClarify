"""Audit a submitted smoke run, then schedule bounded FDB30 replay and scoring."""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys
import time


MANIFEST_SHA256 = '403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07'
IMAGE = 'docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4'
JOB = re.compile(r'job-\d+-[A-Za-z0-9_-]+')


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def audit_run(run, expected, source):
    """Inspect existing PCM receipts and recordings; never load GPU models."""
    sys.path.insert(0, str(source / 'scripts/remote'))
    from score_duplex import validate_recording

    report = json.loads((run / 'frontend/result.json').read_text())
    if (not report['passed'] or len(report['cases']) != expected
            or report['manifest_sha256'] != MANIFEST_SHA256):
        raise ValueError('Incomplete fixed inference set')
    if report['scope'] != ('smoke' if expected == 3 else 'fixed_fdb30'):
        raise ValueError('Inference scope differs')
    equivalence = report['warmup']['equivalence']
    if (not report['warmup']['passed'] or equivalence != {
            'executed': False, 'status': 'disabled_by_user',
            'comparison_policy': 'disabled_by_user', 'passed': None}):
        raise ValueError('Warmup failed or comparison cancellation was not recorded')
    execution = report['execution']
    if (execution['cpu_threads'], execution['interop_threads'], execution['sensevoice_ncpu'],
            execution['skip_complete_recognition']) != (2, 1, 2, True):
        raise ValueError('Native CPU budget or completion policy differs')
    for budget in [report['x2_execution'], *[json.loads((run / name / 'ready.json').read_text())
                                          for name in ('qwen', 'indextts')]]:
        if (budget['cpu_threads'], budget['interop_threads']) != (2, 1):
            raise ValueError('Backend CPU budget differs')
    if len({case['case_id'] for case in report['cases']}) != expected:
        raise ValueError('Repeated inference case')
    frames = skips = 0
    max_lag = 0.
    for case in report['cases']:
        if not case['passed']:
            raise ValueError('Failed inference case')
        folder = run / 'frontend/samples' / case['subset'] / case['id']
        validate_recording(folder, case['recording'])
        count = 0
        with gzip.open(folder / (case['case_id'] + '.frames.jsonl.gz'), 'rt') as stream:
            for line in stream:
                row = json.loads(line)
                control = row['receipts']['controller']
                thread = control['execution_thread']
                if ((thread['ident'], thread['native_id']) !=
                        (execution['thread_ident'], execution['thread_native_id'])
                        or (thread['cpu_threads'], thread['interop_threads']) != (2, 1)):
                    raise ValueError('Controller left the warmed replay thread or CPU budget')
                omitted = sum(e['kind'] == 'complete_recognition_skipped' for e in control['events'])
                complete = control['service_completion_source'] == 'model_complete'
                if (not control['skip_complete_recognition'] or omitted != int(complete)
                        or complete and control['service_text'] != ''):
                    raise ValueError('Unexpected complete recognition behavior')
                if row['step_id'] != count:
                    raise ValueError('Missing or repeated frontend batch')
                count += 1
                skips += omitted
                max_lag = max(max_lag, row['controller_main_lag_ms'])
        if count != case['frames']:
            raise ValueError('Missing recorded frontend frames')
        frames += count
    return {'passed': True, 'cases': expected, 'frames': frames,
            'complete_recognition_skipped': skips, 'max_controller_main_lag_ms': max_lag,
            'recordings_audited': expected, 'execution': execution}


class Campaign:
    """Persist job identities and advance only after the prior job releases GPUs."""

    def __init__(self, args):
        self.args = args
        self.path = args.output / 'state.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'source_commit': args.source_commit, 'source': str(args.source),
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'smoke_job': args.smoke_job, 'status': 'waiting_smoke'}
        if (self.state['source'] != str(args.source) or self.state['smoke_job'] != args.smoke_job
                or self.state['source_commit'] != args.source_commit):
            raise ValueError('Campaign identity differs from saved state')
        self.deadline = time.monotonic() + 12 * 3600

    def save(self, **fields):
        self.state.update(fields, updated_at=time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
        write_json(self.path, self.state)

    def active(self):
        for attempt, delay in enumerate((0, 5, 15, 30), start=1):
            if delay:
                time.sleep(delay)
            try:
                output = subprocess.check_output(['vc', 'list'], text=True, timeout=45,
                                                 stderr=subprocess.STDOUT)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                detail = exc.output or ''
                if isinstance(detail, bytes):
                    detail = detail.decode(errors='replace')
                self.save(scheduler_query_attempt=attempt,
                          scheduler_query_error=type(exc).__name__ + ': ' + str(exc),
                          scheduler_query_output=detail[-4096:])
                if attempt == 4:
                    raise RuntimeError('Scheduler state unavailable after four attempts') from exc
            else:
                self.save(scheduler_query_attempt=attempt, scheduler_query_error=None,
                          scheduler_query_output=None)
                return set(JOB.findall(output))

    def wait(self, job, marker):
        while True:
            if time.monotonic() > self.deadline:
                raise TimeoutError('Campaign reached its twelve-hour deadline')
            if job not in self.active():
                if not marker.exists() or marker.read_text().strip() != '0':
                    raise RuntimeError('Job ended without successful exit marker: ' + job)
                return
            time.sleep(30)

    def submit(self, phase, command, *, gpus, cpus, memory, output):
        key = phase + '_job'
        if key in self.state:
            return self.state[key]
        if output.exists():
            raise FileExistsError('Refusing to replace existing stage output: ' + str(output))
        if self.active():
            raise RuntimeError('Another scheduled job is active; refusing overlapping submission')
        name = self.args.prefix + '-' + phase
        log = self.args.root / 'submit_logs' / (name + '.log')
        cmd = ['vc', 'submit', '--image', IMAGE, '--partition', 'pdgpu-4090', '--job', name,
               '--num-task', '1', '--cpu-per-task', str(cpus), '--mem-per-task', memory,
               '--gpu-per-task', str(gpus), 'JOB=1:1', str(log), '--cmd', command]
        self.save(status='submitting_' + phase, submission_command=cmd)
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        (self.args.output / (phase + '.submit.txt')).write_text(result.stdout + result.stderr)
        jobs = JOB.findall(result.stdout)
        if result.returncode or len(set(jobs)) != 1:
            raise RuntimeError('Scheduler submission did not return exactly one job ID')
        job = jobs[0]
        self.save(**{key: job}, status='waiting_' + phase)
        return job

    def audit(self, stage, run, expected):
        output = self.args.output / (stage + '.audit.json')
        env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                   PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='')
        subprocess.run([str(self.args.audit_python), str(Path(__file__).resolve()),
                        '--source', str(self.args.source), '--audit-run', str(run),
                        '--expected-cases', str(expected), '--audit-output', str(output)],
                       env=env, check=True, timeout=120)
        self.save(**{stage + '_audit': str(output)})

    def run(self):
        a = self.args
        self.save()
        self.wait(a.smoke_job, a.smoke_run / 'exit_code.txt')
        self.audit('smoke', a.smoke_run, 3)
        formal = a.root / 'runs' / (a.prefix + '-formal')
        command = ' '.join(['env', 'SOULX_SOURCE=' + shlex.quote(str(a.source)),
                            'SOULX_RUN_ID=' + shlex.quote(formal.name), 'SOULX_MODE=formal',
                            'timeout --signal=TERM --kill-after=10 7200 bash',
                            shlex.quote(str(a.source / 'scripts/remote/run_fdb30_half_duplex.sh'))])
        job = self.submit('formal', command, gpus=3, cpus=12, memory='64G', output=formal)
        self.wait(job, formal / 'exit_code.txt')
        self.audit('formal', formal, 30)
        score = a.root / 'analysis' / (a.prefix + '-score')
        marker = a.output / 'score.exit_code.txt'
        score_command = ['env', '-u', 'PYTHONNOUSERSITE', 'NUMBA_CUDA_USE_NVIDIA_BINDING=0',
                         'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1', 'OMP_NUM_THREADS=4',
                         'MKL_NUM_THREADS=4', 'OPENBLAS_NUM_THREADS=4', 'NUMEXPR_NUM_THREADS=4',
                         'PYTHONDONTWRITEBYTECODE=1', 'timeout', '--signal=TERM', '--kill-after=10', '3600',
                         str(a.root.parent / 'miniconda3/envs/full-duplex-bench/bin/python'),
                         str(a.source / 'scripts/remote/score_fdb30_half_duplex.py'),
                         '--run', str(formal / 'frontend'), '--output', str(score),
                         '--assets', str(a.root.parent / 'turncontrol-comparison'),
                         '--fdb-repo', str(a.root.parent / 'Full-Duplex-Bench')]
        command = ('ntf_score_code=0\n' + shlex.join(score_command)
                   + ' || ntf_score_code=$?\nprintf \'%s\\n\' "$ntf_score_code" > '
                   + shlex.quote(str(marker)) + '\nexit "$ntf_score_code"')
        job = self.submit('score', command, gpus=1, cpus=4, memory='32G', output=score)
        self.wait(job, marker)
        summary = json.loads((score / 'summary.json').read_text())
        if len(summary['rows']) != 30 or summary['judge_status'] != 'excluded_by_user':
            raise ValueError('Final scoring scope differs')
        self.save(status='complete', formal_run=str(formal), score_output=str(score))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-commit')
    parser.add_argument('--audit-run', type=Path)
    parser.add_argument('--expected-cases', type=int, choices=(3, 30))
    parser.add_argument('--audit-output', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--audit-python', type=Path)
    parser.add_argument('--smoke-run', type=Path)
    parser.add_argument('--smoke-job')
    parser.add_argument('--prefix')
    args = parser.parse_args()
    if not (Path(sys.prefix) / 'conda-meta/history').is_file():
        parser.error('Use a remote conda environment')
    if args.audit_run:
        if not args.expected_cases or not args.audit_output:
            parser.error('Audit mode requires case count and output')
        write_json(args.audit_output, audit_run(args.audit_run, args.expected_cases, args.source))
        return
    if not all((args.root, args.output, args.audit_python, args.smoke_run, args.smoke_job, args.prefix)):
        parser.error('Campaign arguments are incomplete')
    if not JOB.fullmatch(args.smoke_job) or not re.fullmatch(r'[a-z0-9_-]{1,55}', args.prefix):
        parser.error('Invalid campaign identity')
    if not args.source_commit or not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
        parser.error('Campaign requires the frozen source commit')
    if subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip() != args.source_commit:
        parser.error('Model source commit differs')
    if subprocess.check_output(['git', '-C', str(args.source), 'status', '--porcelain'], text=True).strip():
        parser.error('Model source worktree is dirty')
    resource.setrlimit(resource.RLIMIT_AS, (2 * 2**30, 2 * 2**30))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'campaign.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        campaign = Campaign(args)
        try:
            campaign.run()
        except BaseException as exc:
            campaign.save(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            raise


if __name__ == '__main__':
    main()
