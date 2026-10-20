"""Verify weighted training, exact restart and clean inference on one scheduled GPU."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import yaml

from layer1_data import write_json
from layer1_model import load_official_checkpoint, sha256_file
from train_layer1 import check_disk


def verify_candidate(args):
    """Check full candidates or explicitly diagnostic probes without changing eligibility."""
    from layer1_candidate import load_candidate
    loaded = load_official_checkpoint(args.checkpoint, args.base_model, training=False)
    report = load_candidate(loaded, args.candidate, args.checkpoint, args.base_model,
                            verification_only=not args.formal)
    if report['inference_eligible'] != args.formal:
        raise ValueError('Candidate eligibility differs from the requested verification mode')
    write_json(args.output, report)
    return report


def main(args):
    root, output = args.root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = yaml.safe_load((root / 'configs/layer1_alignment_protocol.yaml').read_text())
    budget = protocol['probe']
    started = time.monotonic()
    checkpoint = args.model_home / 'sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28'
    base = args.model_home / 'Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a'
    dataset = args.training_root / 'data/runs/issue004-build-r5'
    trainer = root / 'scripts/training/train_layer1.py'
    common = [sys.executable, '-u', str(trainer), 'train', '--checkpoint', str(checkpoint),
              '--base-model', str(base), '--official-source', str(args.official_source),
              '--inventory', str(root / 'reports/layer1_training/issue001-inventory-20261018/inventory_summary.json'),
              '--dataset', str(dataset / 'dataset'), '--audit', str(dataset / 'audit.json'),
              '--config', str(root / 'configs/layer1_alignment_training.yaml'),
              '--protocol', str(root / 'configs/layer1_alignment_protocol.yaml'),
              '--arm', 'T2', '--dialogues', '1000', '--length', '2048', '--alignment-probe']
    phases = []

    def run(name, command, seconds=900):
        check_disk(output, budget)
        remaining = budget['max_wall_seconds'] - (time.monotonic() - started)
        if remaining < 1:
            raise RuntimeError('Alignment overall wall budget exhausted')
        tick = time.monotonic()
        with (output / (name + '.log')).open('x') as log:
            child = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=30',
                        str(max(1, min(seconds, int(remaining)))), *command], cwd=root,
                        stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        row = {'name': name, 'exit_code': child.returncode, 'wall_seconds': time.monotonic() - tick,
               'max_rss_kib': usage.ru_maxrss, 'user_seconds': usage.ru_utime, 'system_seconds': usage.ru_stime}
        phases.append(row)
        write_json(output / 'phases.json', phases)
        print(json.dumps(row), flush=True)
        check_disk(output, budget)
        if child.returncode:
            raise RuntimeError('Alignment phase failed: ' + name)

    try:
        for pattern in ('test_layer1_training.py', 'test_layer1_alignment.py',
                        'test_layer1_adaptation.py', 'test_layer1_candidate.py'):
            run(pattern, [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', pattern, '-v'], 120)
        for name, steps, resume in (('continuous', 8, None), ('interrupted', 4, None),
                                    ('resumed', 8, output / 'interrupted/checkpoint.pt'),
                                    ('sustained', 100, None)):
            command = common + ['--steps', str(steps), '--output', str(output / name)]
            if resume:
                command += ['--resume', str(resume)]
            run(name, command)
        run('recovery', [sys.executable, str(trainer), 'compare', '--continuous', str(output / 'continuous'),
                         '--resumed', str(output / 'resumed'), '--output', str(output / 'recovery.json')], 120)
        run('inference', [sys.executable, str(Path(__file__)), 'verify', '--checkpoint', str(checkpoint),
                          '--base-model', str(base), '--candidate', str(output / 'sustained/checkpoint.pt'),
                          '--output', str(output / 'inference.json')])
        summaries = {name: json.loads((output / name / 'summary.json').read_text())
                     for name in ('continuous', 'interrupted', 'resumed', 'sustained')}
        manifest = json.loads((output / 'sustained/manifest.json').read_text())
        config = manifest['identity']['config']
        saved_bytes = summaries['sustained']['checkpoint']['bytes']
        projected_output = saved_bytes * 6 + 64 * 1024**2
        peak_reserved = max(row['peak_reserved_bytes'] for row in summaries.values())
        max_rss = max(row['max_rss_kib'] for row in phases)
        import torch
        capacity = torch.cuda.get_device_properties(0).total_memory
        resources_passed = (peak_reserved < capacity and max_rss * 1024 < 32 * 1024**3 and
                            projected_output < config['max_output_gib'] * 1024**3)
        recovery = json.loads((output / 'recovery.json').read_text())
        inference = json.loads((output / 'inference.json').read_text())
        report = {'passed': resources_passed and recovery['passed'] and
                  inference['complete_inference_weights_match_training'] and inference['clean_process_probe_ids_match'],
                  'recovery_passed': recovery['passed'], 'inference_reload_passed':
                  inference['complete_inference_weights_match_training'] and inference['clean_process_probe_ids_match'],
                  'resource_passed': resources_passed, 'config_sha256': sha256_file(root / 'configs/layer1_alignment_training.yaml'),
                  'index_sha256': protocol['full_train_index_sha256'], 'code': manifest['identity']['code'],
                  'job_id': os.environ.get('JobID'), 'source_commit': manifest['source_commit'],
                  'probe_only': True, 'formal_training_executed': False, 'condition': config['condition'],
                  'peak_reserved_bytes': peak_reserved, 'device_total_bytes': capacity, 'max_rss_kib': max_rss,
                  'checkpoint_bytes': saved_bytes, 'projected_formal_output_bytes': projected_output,
                  'output_bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
                  'wall_seconds': time.monotonic() - started, 'phases': phases,
                  'resources': budget, 'training_budget': {'gpus': 1, 'cpus': 8, 'memory_gib': 32,
                    'concurrent_jobs': 1, 'workers': 0, 'max_wall_seconds': 28800,
                    'max_output_gib': 5, 'min_free_gib': 5, 'checkpoint_steps': [203, 406, 609, 812, 1015, 1214]},
                  'sustained_summary': summaries['sustained'], 'exact_recovery': recovery,
                  'inference_reload': inference}
        write_json(output / 'release.json', report)
        if not report['passed']:
            raise RuntimeError('Alignment resource/recovery/inference gate failed')
        return report
    except Exception as error:
        write_json(output / 'failure.json', {'passed': False, 'error': f'{type(error).__name__}: {error}',
                                            'phases': phases})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    for key in ('root', 'output', 'training-root', 'model-home', 'official-source'):
        run.add_argument('--' + key, type=Path, required=True)
    verify = sub.add_parser('verify')
    for key in ('checkpoint', 'base-model', 'candidate', 'output'):
        verify.add_argument('--' + key, type=Path, required=True)
    verify.add_argument('--formal', action='store_true', help='Require a complete formal final-epoch candidate')
    args = parser.parse_args()
    report = verify_candidate(args) if args.command == 'verify' else main(args)
    print(json.dumps(report), flush=True)
