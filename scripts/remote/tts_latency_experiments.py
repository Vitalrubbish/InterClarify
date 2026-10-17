"""Run small, single-variable TTS screens sequentially on one allocated GPU."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import tts_latency_benchmark as bench


def arms():
    """Declare the control for each candidate without enabling product defaults."""
    modes = ['whole', 'incremental', 'sparse']
    common = {'batch': 0, 'early': 0, 'tokens': 12, 'wait_ms': 0}
    return [
        dict(common, name='control_start', control=None, modes=modes),
        dict(common, name='batch4', batch=4, control='control_start', modes=modes[:2]),
        dict(common, name='early_batch4', batch=4, early=1, control='batch4', modes=modes[:2]),
        dict(common, name='prefill8', tokens=8, control='control_start', modes=['sparse']),
        dict(common, name='prefill4', tokens=4, control='control_start', modes=['sparse']),
        dict(common, name='deadline200', wait_ms=200, control='control_start', modes=['sparse']),
        dict(common, name='control_end', control='control_start', modes=modes),
    ]


def write_json(path, value):
    """Publish a complete JSON snapshot for the external monitor."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def stop_process(process):
    """Stop this job's process group, bounding cleanup even during startup."""
    if process is None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def wait_health(port, process, timeout=600):
    """Require the actual server to become ready before scheduling text."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Service exited with {process.returncode}')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise TimeoutError('Service health timeout')


async def run_arm(args, arm, items, corpus_path, progress):
    """Warm each selected input before recording this candidate's screen."""
    output = args.output / arm['name']
    output.mkdir()
    (output / 'warmup').mkdir()
    env = os.environ.copy()
    env.update({
        'XTALK_TTS_TRACE': str(output / 'server.jsonl'),
        'XTALK_TTS_METRICS': '1', 'XTALK_TTS_SEED': '17',
        'XTALK_TTS_CODEC_LOAD_THREADS': '1', 'XTALK_TTS_STACK_DIAGNOSTIC': '0',
        'XTALK_TTS_GENERATION_BATCH_FRAMES': str(arm['batch']),
        'XTALK_TTS_EARLY_COMPILE': str(arm['early']),
        'XTALK_TTS_PREFILL_TEXT_TOKENS': str(arm['tokens']),
        'XTALK_TTS_PREFILL_MAX_WAIT_MS': str(arm['wait_ms']),
        'XTALK_TTS_LOCAL_ATTN': 'sdpa', 'XTALK_TTS_LOCAL_COMPILE': 'inductor',
        'XTALK_TTS_SAMPLE': 'upstream', 'TORCH_LOGS': 'recompiles',
        'XTALK_MOSS_SOURCE_ROOT': str(args.round1_root / 'moss-source'),
        'XTALK_MOSS_SERVICE_ROOT': str(args.round1_root / 'moss-service'),
        'XTALK_ROUND1_ROOT': str(args.round1_root),
        'TMPDIR': str(output / 'tmp'),
    })
    Path(env['TMPDIR']).mkdir()
    write_json(output / 'arm.json', {'configuration': arm, 'service_environment': {
        k: v for k, v in env.items() if k.startswith('XTALK_TTS_') or k == 'TORCH_LOGS'}})
    settings = SimpleNamespace(url=f'ws://127.0.0.1:{args.port}/tts/ws',
        reference=str(args.reference), timeout=600, corpus=corpus_path,
        repeats=3, output=output / 'measured', server_trace=output / 'server.jsonl',
        probe=False, screening=True, modes=arm['modes'])
    process = None
    with (output / 'service.log').open('w') as log:
        try:
            command = [sys.executable, str(args.task_root / 'scripts/remote/run_xtalk_round1.py'),
                       '--model-root', str(args.model_root), 'serve', 'tts',
                       '--gpu-index', '0', '--port', str(args.port)]
            process = subprocess.Popen(command, cwd=args.task_root, env=env,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            await asyncio.to_thread(wait_health, args.port, process)
            for item in items:
                for mode in arm['modes']:
                    progress.update(current_arm=arm['name'], phase='warmup', text=item['id'], mode=mode)
                    write_json(args.output / 'progress.json', progress)
                    row = await bench.run_case(settings, item, mode, 'warmup', output / 'warmup')
                    if row['error'] or not row['samples']:
                        raise RuntimeError(f'Warmup failed: {row}')
            progress.update(phase='measured')
            write_json(args.output / 'progress.json', progress)
            result = await bench.run(settings)
            if result:
                raise RuntimeError(f'Measured response failure; see {settings.output}')
            return json.loads((settings.output / 'summary.json').read_text())
        finally:
            stop_process(process)


async def run(args):
    """Keep comparable controls and preserve intermediate results on failure."""
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ('inductor', 'triton'):
        path = args.output / 'cache' / name
        path.mkdir(parents=True)
        os.environ['TORCHINDUCTOR_CACHE_DIR' if name == 'inductor' else 'TRITON_CACHE_DIR'] = str(path)
    items = [bench.corpus()[i] for i in (0, 18, 34)]
    corpus_path = args.output / 'screen_corpus.jsonl'
    corpus_path.write_text(''.join(json.dumps(item) + '\n' for item in items))
    write_json(args.output / 'manifest.json', bench.manifest())
    (args.output / 'models.lock.json').write_bytes((args.model_root / 'models.lock.json').read_bytes())
    subprocess.run(['nvidia-smi', '--query-gpu=uuid,name,driver_version,memory.total', '--format=csv'],
                   stdout=(args.output / 'gpu_identity.txt').open('w'), check=True)
    progress = {'current_arm': None, 'phase': 'starting', 'completed': [], 'failed': []}
    reports = {}
    sampler = None
    with (args.output / 'gpu.csv').open('w') as gpu_log:
        try:
            sampler = subprocess.Popen(['nvidia-smi', '--query-gpu=timestamp,uuid,name,memory.used,utilization.gpu',
                '--format=csv', '-l', '1'], stdout=gpu_log, stderr=subprocess.STDOUT, start_new_session=True)
            for arm in arms():
                progress.update(current_arm=arm['name'], phase='startup')
                write_json(args.output / 'progress.json', progress)
                try:
                    reports[arm['name']] = await run_arm(args, arm, items, corpus_path, progress)
                    progress['completed'].append(arm['name'])
                except Exception as error:
                    progress['failed'].append({'arm': arm['name'], 'error': f'{type(error).__name__}: {error}'})
                write_json(args.output / 'experiment_summary.json', {'progress': progress, 'arms': reports})
                print(json.dumps(progress), flush=True)
            progress.update(phase='finished')
            write_json(args.output / 'progress.json', progress)
            write_json(args.output / 'experiment_summary.json', {'progress': progress, 'arms': reports})
        finally:
            stop_process(sampler)
    return int(bool(progress['failed']))


def main():
    """Run only inside a scheduler allocation and an existing conda environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('task-root', 'output', 'round1-root', 'model-root', 'reference'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--port', type=int, default=18004)
    args = parser.parse_args()
    for name in ('task_root', 'output', 'round1_root', 'model_root', 'reference'):
        setattr(args, name, getattr(args, name).resolve())
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
