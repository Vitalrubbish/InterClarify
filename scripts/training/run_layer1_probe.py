"""Orchestrate serial, time-bounded GPU probes in independent training processes."""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from layer1_data import write_json


def main(args):
    root, output = args.root.resolve(), args.output.resolve()
    trainer = root / 'scripts/training/train_layer1.py'
    checkpoint = args.model_home / 'sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28'
    base = args.model_home / 'Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a'
    dataset = args.training_root / 'data/runs/issue004-build-r5'
    common = [sys.executable, '-u', str(trainer), 'train', '--checkpoint', str(checkpoint),
              '--base-model', str(base), '--official-source', str(args.official_source),
              '--inventory', str(root / 'reports/layer1_training/issue001-inventory-20261018/inventory_summary.json'),
              '--dataset', str(dataset / 'dataset'), '--audit', str(dataset / 'audit.json'),
              '--config', str(root / 'configs/layer1_training.yaml')]
    phases = []

    def run(name, command, seconds=900):
        started = time.monotonic()
        with (output / (name + '.log')).open('w') as log:
            child = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=30', str(seconds), *command],
                                     cwd=root, stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        row = {'name': name, 'exit_code': child.returncode, 'wall_seconds': time.monotonic() - started,
               'max_rss_kib': usage.ru_maxrss, 'user_seconds': usage.ru_utime, 'system_seconds': usage.ru_stime}
        phases.append(row)
        write_json(output / 'phases.json', phases)
        print(json.dumps(row), flush=True)
        return row

    tests = run('training-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                                   '-p', 'test_layer1_training.py', '-v'], 120)
    if tests['exit_code']:
        raise RuntimeError('Training state contract tests failed')
    for name, steps, resume in (('continuous32', 4, None), ('interrupted32', 2, None),
                                ('resumed32', 4, output / 'interrupted32/checkpoint.pt')):
        command = common + ['--dialogues', '32', '--length', '256', '--steps', str(steps),
                            '--output', str(output / name)]
        if resume:
            command += ['--resume', str(resume)]
        if run(name, command)['exit_code']:
            raise RuntimeError('Real model update/recovery failed: ' + name)
    comparison = run('recovery-comparison', [sys.executable, str(trainer), 'compare',
                     '--continuous', str(output / 'continuous32'), '--resumed', str(output / 'resumed32'),
                     '--output', str(output / 'recovery.json')], 120)
    if comparison['exit_code']:
        raise RuntimeError('Exact uninterrupted/restarted training comparison failed')
    successes, failures = [], []
    for length in (256, 512, 1024, 2048, 4096):
        name = 'resource100-' + str(length)
        phase = run(name, common + ['--dialogues', '100', '--length', str(length), '--steps', '6',
                                   '--output', str(output / name)], 900)
        if phase['exit_code']:
            log = (output / (name + '.log')).read_text()
            phase['oom'] = 'OutOfMemoryError' in log or 'CUDA out of memory' in log
            failures.append(phase)
            if not phase['oom']:
                write_json(output / 'unexpected_failure.json', phase)
                raise RuntimeError('Non-OOM resource failure: ' + name)
        else:
            summary = json.loads((output / name / 'summary.json').read_text())
            manifest = json.loads((output / name / 'manifest.json').read_text())
            successes.append({'length': length, 'phase': phase, 'summary': summary,
                              'identity': manifest['identity']})
    # Retain memory headroom instead of selecting the largest barely passing window.
    safe = [r for r in successes if r['summary']['peak_reserved_bytes'] <= 22 * 1024**3]
    if not safe:
        raise RuntimeError('No resource configuration has 2 GiB memory headroom')
    selected = max(safe, key=lambda r: r['length'])
    index_phase = run('full-train-index', [sys.executable, str(trainer), 'index',
                      '--dataset', str(dataset / 'dataset'), '--audit', str(dataset / 'audit.json'),
                      '--tokenizer', str(checkpoint / 'tokenizer'), '--length', str(selected['length']),
                      '--output', str(output / 'full_train_index.json')], 900)
    if index_phase['exit_code']:
        raise RuntimeError('Full train indexing failed')
    full_index = json.loads((output / 'full_train_index.json').read_text())
    per_step = selected['summary']['loop_seconds'] / 6
    per_dialogue_sequences = selected['summary']['data_statistics']['sequences'] / 100
    estimates = []
    for dialogues, per_arm_cap in ((1000, 8), (3000, 16)):
        steps = (math.ceil(full_index['T3']['statistics']['sequences'] / 2) if dialogues == 1000 else
                 math.ceil(dialogues * per_dialogue_sequences / 2))
        estimates.append({'dialogues_per_arm': dialogues, 'estimated_steps_per_arm': steps,
                          'estimated_training_gpu_hours_per_arm': steps * per_step / 3600,
                          'gpu_hours_cap_per_arm': per_arm_cap,
                          'estimate_basis': ('exact 1000-dialogue T3 index' if dialogues == 1000 else
                                             '100-dialogue sequence density; 3000 not built'),
                          'excludes': 'evaluation, startup and checkpoint selection'})
    report = {'passed': True, 'recovery_passed': True, 'resource_successes': [r['length'] for r in successes],
              'resource_failures': failures, 'selected_length': selected['length'],
              'batch_size': 1, 'gradient_accumulation': 2, 'estimated_budgets': estimates,
              'formal_training_released': False, 'exact_full_train_steps_pending': False,
              'full_train_statistics': {arm: item['statistics'] for arm, item in full_index.items()},
              'note': 'Final partial accumulation is required if the sequence count is odd; 3000 not built.'}
    write_json(output / 'summary.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'output', 'training-root', 'model-home', 'official-source'):
        parser.add_argument('--' + key, type=Path, required=True)
    print(json.dumps(main(parser.parse_args())), flush=True)
