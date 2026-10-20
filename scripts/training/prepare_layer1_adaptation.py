"""Prepare auditable B0/T1/T2/T3 plans without submitting training jobs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml

from layer1_model import sha256_file


ARMS = ('T1', 'T2', 'T3')
ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_blockers(protocol, root):
    """Require preregistered evaluation assets before any formal optimization."""
    blockers = []
    if protocol.get('training_released') is not True:
        blockers.append('training_released is not true')
    gates = protocol.get('gates', {})
    for key in ('issue001_runtime_comparison', 'issue004_data_audit',
                'issue005_zero_update_and_recovery', 'issue007_pretraining_preparation'):
        if gates.get(key) != 'passed':
            blockers.append(key + ' is not passed')
    if not protocol.get('acceptance', {}).get('sample_manifest'):
        blockers.append('acceptance.sample_manifest is missing')
    assets = protocol.get('evaluation_assets', {})
    for key in ('sample_manifest', 'acceptance_config', 'evaluator'):
        item = assets.get(key) or {}
        if not isinstance(item, dict) or not item.get('path') or not item.get('sha256'):
            blockers.append('evaluation_assets.' + key + ' is not frozen')
            continue
        path = root / item['path']
        if not path.is_file() or sha256_file(path) != item['sha256']:
            blockers.append('evaluation_assets.' + key + ' digest mismatch or missing file')
        if key == 'sample_manifest' and item['path'] != protocol.get('acceptance', {}).get('sample_manifest'):
            blockers.append('evaluation sample manifest references disagree')
    return blockers


def validate_formal_config(config, protocol, root, arm, dialogues, length, steps):
    """Keep the released first-round budget identical across training arms."""
    require(config['purpose'] == 'issue006_round1' and config['schema_version'] == 1,
            'Invalid formal training configuration')
    require(arm in ARMS, 'B0 never trains; choose T1/T2/T3')
    training = protocol['training']
    require(dialogues == training['round1_max_dialogues'] == 1000, 'Round-one dialogue budget mismatch')
    require(length == training['sequence_length'] == 512, 'Registered window mismatch')
    require(steps == config['scheduler_steps'] == training['actual_steps'] == 5763,
            'Formal training must complete the registered single epoch')
    require(config['batch_size'] == training['actual_batch'] == 1 and
            config['gradient_accumulation'] == training['gradient_accumulation'] == 2,
            'Registered effective batch mismatch')
    require(config['seed'] == training['seed'], 'Registered seed mismatch')
    require(0 < config['warmup_steps'] < steps and config['save_every_steps'] > 0,
            'Invalid scheduler or save interval')
    require(0 < config['max_wall_seconds'] <= training['max_gpu_hours_per_condition'][0] * 3600,
            'GPU wall-time budget exceeded')
    require(training['initialization'] == 'complete_official_checkpoint' and
            training['trainable'] == 'existing_q_v_lora_only', 'Unsupported initialization/update scope')
    registered = training.get('round1_optimizer', {})
    for key in ('learning_rate', 'weight_decay', 'adam_betas', 'adam_eps', 'max_grad_norm',
                'scheduler_steps', 'warmup_steps', 'save_every_steps'):
        require(config[key] == registered.get(key), 'Optimizer preregistration mismatch: ' + key)
    blockers = release_blockers(protocol, root)
    require(not blockers, 'Formal training blocked: ' + '; '.join(blockers))


def validate_index(index, protocol):
    """Reject incomparable event plans or hidden mixed-arm duplicate exposure."""
    require(set(index) == set(ARMS), 'Exactly three training indices are required')
    baseline = index['T1']
    training = protocol['training']
    for arm in ARMS:
        row = index[arm]
        require(row['arm'] == arm, 'Index arm mismatch')
        for key in ('subset', 'manifest_sha256', 'audit_sha256', 'length'):
            require(row[key] == baseline[key], 'Cross-arm data mismatch: ' + key)
        require(len(row['subset']) == len(set(row['subset'])) == 1000, 'Duplicate/missing train dialogues')
        require(row['length'] == training['sequence_length'], 'Index window mismatch')
        stats = row['statistics']
        require(stats['sequences'] == training['round1_sequences_per_condition'], 'Sequence count mismatch')
        require(stats['effective_tokens'] == training['round1_effective_tokens_per_condition'],
                'Supervision budget mismatch')
        require(math.ceil(stats['sequences'] / training['effective_batch']) == training['actual_steps'],
                'Optimizer step budget mismatch')
    require(index['T1']['statistics'].get('view_original') == 1000 and
            index['T2']['statistics'].get('view_unpunctuated') == 1000, 'Single-view assignment mismatch')
    require(index['T3']['statistics'].get('view_original') == 500 and
            index['T3']['statistics'].get('view_unpunctuated') == 500, 'T3 must contain 500/500 dialogues')


def build_plan(protocol_path, config_path, root=ROOT):
    protocol = yaml.safe_load(protocol_path.read_text())
    config = yaml.safe_load(config_path.read_text())
    index_path = root / protocol['training']['full_train_index']
    index = json.loads(index_path.read_text())
    validate_index(index, protocol)
    blockers = release_blockers(protocol, root)
    # Validate parameter registration even while release gates remain closed.
    try:
        validate_formal_config(config, protocol, root, 'T1', 1000, 512, 5763)
    except ValueError as error:
        if not str(error).startswith('Formal training blocked:'):
            raise
    checkpoints = list(range(config['save_every_steps'], config['scheduler_steps'], config['save_every_steps']))
    checkpoints.append(config['scheduler_steps'])
    inventory = root / protocol['assets']['verified_inventory']
    conditions = {'B0': {'updates': False, 'initialization': 'complete_official_checkpoint',
                          'checkpoint_steps': [0], 'dev_views': ['original', 'unpunctuated']}}
    for arm in ARMS:
        conditions[arm] = {'updates': True, 'initialization': 'complete_official_checkpoint',
                           'index': index[arm], 'checkpoint_steps': checkpoints,
                           'dev_views': ['original', 'unpunctuated'],
                           'max_gpu_hours': protocol['training']['max_gpu_hours_per_condition'][0]}
    return {'schema_version': 1, 'issue': '006', 'training_released': not blockers,
            'blockers': blockers, 'conditions': conditions, 'training_config': config,
            'inputs': {str(path.relative_to(root) if path.is_relative_to(root) else path): sha256_file(path) for path in
                       (protocol_path, config_path, index_path, inventory)},
            'assets': protocol['assets'], 'data': protocol['data'],
            'runtime': protocol['runtime'], 'evaluation_assets': protocol.get('evaluation_assets', {}),
            'selection': 'dev only; each model generates its own history; no test/FDB selection',
            'resources': {'gpus': 1, 'cpus': 8, 'memory_gib': 32, 'concurrent_jobs': 1,
                          'max_output_gib_per_arm': config['max_output_gib']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, default=ROOT / 'configs/layer1_adaptation_protocol.yaml')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/layer1_adaptation_training.yaml')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-release', action='store_true')
    args = parser.parse_args()
    plan = build_plan(args.protocol.resolve(), args.config.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'training_released': plan['training_released'], 'blockers': plan['blockers']}))
    if args.require_release and not plan['training_released']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
