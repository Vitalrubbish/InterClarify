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
    """Release training from technical evidence and a fixed final-epoch policy."""
    blockers = []
    if protocol.get('training_released') is not True:
        blockers.append('training_released is not true')
    gates = protocol.get('gates', {})
    for key in ('issue001_runtime_comparison', 'issue004_data_audit',
                'issue005_zero_update_and_recovery'):
        if gates.get(key) != 'passed':
            blockers.append(key + ' is not passed')
    if protocol.get('training', {}).get('checkpoint_selection') != 'final_epoch':
        blockers.append('checkpoint_selection must be final_epoch')
    return blockers


def validate_formal_config(config, protocol, root, arm, dialogues, length, steps):
    """Keep the released first-round budget identical across training arms."""
    require(config['purpose'] == 'issue006_round1' and config['schema_version'] == 1,
            'Invalid formal training configuration')
    require(arm in ARMS, 'B0 never trains; choose T1/T2/T3')
    training = protocol['training']
    require(dialogues == config['dialogues'] == training['round1_max_dialogues'] == 1000,
            'Round-one dialogue budget mismatch')
    require(length == config['sequence_length'] == training['sequence_length'], 'Registered window mismatch')
    require(steps == config['scheduler_steps'] == training['actual_steps'] and steps > 0,
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


def validate_alignment_config(config, protocol, root, arm, dialogues, length, steps, probe=False):
    """Freeze the second-round deltas and require actual recovery/resource evidence."""
    from layer1_loss import CONTROL_WEIGHTS
    require(config.get('purpose') == 'issue036_alignment' and config['schema_version'] == 1,
            'Invalid alignment purpose/schema')
    require(protocol['schema_version'] == 1 and protocol['issue'] == '036', 'Invalid alignment protocol')
    require(config['condition'] == protocol['condition'] == 'T2_R2_paper_aligned', 'Condition mismatch')
    require(arm == 'T2' and dialogues == config['dialogues'] == 1000 and
            length == config['sequence_length'] == 2048, 'Alignment requires the frozen full T2 index')
    parent_path = root / protocol['parent_protocol']
    require(sha256_file(parent_path) == protocol['parent_protocol_sha256'], 'Parent protocol changed')
    parent = yaml.safe_load(parent_path.read_text())
    index = root / parent['training']['full_train_index']
    require(sha256_file(index) == protocol['full_train_index_sha256'], 'Frozen full index changed')
    validate_index(json.loads(index.read_text()), parent)
    baseline = yaml.safe_load((root / 'configs/layer1_adaptation_training.yaml').read_text())
    expected = {**baseline, 'purpose': 'issue036_alignment', 'condition': 'T2_R2_paper_aligned',
                'warmup_steps': math.ceil(baseline['scheduler_steps'] * 0.1),
                'loss': {'type': 'control_weighted_ce', 'control_weights': CONTROL_WEIGHTS, 'chunk_size': 64}}
    require(config == expected, 'Alignment differs outside registered loss/warmup deltas')
    # Use canonical YAML identity only at the input path; the caller checks the actual file digest.
    require(not release_blockers(parent, root), 'Parent technical release gates are closed')
    require(protocol['probe'] == dict(max_steps=100, max_wall_seconds=3600, max_output_gib=16,
            min_free_gib=15, gpus=1, cpus=8, memory_gib=32, workers=0), 'Probe resource budget changed')
    if probe:
        require(0 < steps <= protocol['probe']['max_steps'], 'Alignment probe is limited to 100 steps')
    else:
        require(steps == config['scheduler_steps'], 'Formal alignment must complete the final epoch')
        require(protocol.get('training_released') is True, 'Alignment training blocked: resource release pending')
        if protocol.get('release_policy') == 'user_waived_alignment_probe':
            require(protocol.get('probe_waiver') == {
                'date': '2026-10-20', 'decision': 'skip_alignment_probe_and_start_formal_t2',
                'scope': 'alignment_resource_recovery_inference_short_runs_only'},
                'Invalid explicit user probe waiver')
            return parent
        path = root / protocol['resource_report']
        require(protocol.get('resource_report_sha256') and path.is_file() and
                sha256_file(path) == protocol['resource_report_sha256'], 'Alignment release evidence missing/changed')
        report = json.loads(path.read_text())
        require(all(report.get(key) is True for key in
                    ('passed', 'recovery_passed', 'inference_reload_passed', 'resource_passed')),
                'Alignment release checks failed')
        require(report.get('config_sha256') == protocol['training_config_sha256'] and
                report.get('index_sha256') == protocol['full_train_index_sha256'],
                'Alignment release identity mismatch')
        for name, value in report.get('code', {}).items():
            require(sha256_file(root / 'scripts/training' / name) == value, 'Released training code changed')
        require(set(report.get('code', {})) == {'train_layer1.py', 'layer1_data.py', 'layer1_model.py',
                'number_surface.py', 'layer1_loss.py', 'prepare_layer1_adaptation.py', 'layer1_candidate.py'},
                'Incomplete released source identity')
    return parent



def validate_delayed_config(config, protocol, root, arm, dialogues, length, steps):
    """Authorize one frozen delayed-start epoch from the latest machine-audited data."""
    require(protocol['schema_version'] == 1 and protocol['issue'] == '040'
            and protocol.get('training_released') is True, 'Delayed training is not released')
    require(protocol.get('authorization') == {
        'date': '2026-10-20', 'decision': 'direct_full_training_latest_data_weighted_loss',
        'additional_epochs': 1, 'pretraining_model_probe': 'not_required_by_user_direct_training',
        'human_review': 'pending_not_claimed_passed'}, 'Missing current direct-training authorization')
    parent_path = root / protocol['parent_protocol']
    require(sha256_file(parent_path) == protocol['parent_protocol_sha256'], 'Parent protocol changed')
    parent = yaml.safe_load(parent_path.read_text())
    require(not release_blockers(parent, root), 'Parent technical gates are closed')
    baseline = yaml.safe_load((root / 'configs/layer1_alignment_training.yaml').read_text())
    expected = {**baseline, 'purpose': 'issue040_delayed_start', 'condition': 'T2_R3_delayed_start',
                'scheduler_steps': 1235, 'warmup_steps': 124, 'save_every_steps': 206}
    require(config == expected and config['condition'] == protocol['condition'],
            'Delayed training differs from the frozen weighted configuration')
    require(arm == 'T2' and dialogues == 1000 and length == 2048 and steps == 1235,
            'Delayed training requires the full single T2 epoch')
    require(protocol['resources'] == dict(gpus=1, cpus=8, memory_gib=32, workers=0,
            concurrent_jobs=1, max_wall_seconds=28800, training_output_gib=5,
            total_output_gib=6, min_free_gib=5), 'Delayed resource budget changed')
    audit_path = root / 'reports/layer1_training/issue040-delayed-start-data-20261020/audit.json'
    audit = json.loads(audit_path.read_text())
    require(sha256_file(audit_path) == protocol['data_audit_sha256'] and audit['machine_passed']
            and audit['manifest_sha256'] == protocol['data_manifest_sha256']
            and audit['response_start_timing'] == 'next_no_voice'
            and audit['baseline_comparison']['content_and_random_events_unchanged'],
            'Latest delayed dataset audit changed')
    index_path = root / protocol['training']['full_train_index']
    require(protocol.get('full_train_index_sha256') and
            sha256_file(index_path) == protocol['full_train_index_sha256'], 'Delayed full index changed')
    index = json.loads(index_path.read_text())
    effective = {**parent, 'training': {**parent['training'], **protocol['training']},
                 'post_training_evaluation': {**parent['post_training_evaluation'],
                     'conditions': ['T2_R3_delayed_start'],
                     'reference_conditions': ['T2', 'T2_R2_paper_aligned'], 'automatic_submit': False}}
    validate_index(index, effective)
    for row in index.values():
        require(row['manifest_sha256'] == protocol['data_manifest_sha256']
                and row['audit_sha256'] == protocol['data_audit_sha256'], 'Index uses an older dataset')
    require(effective['training']['checkpoint_selection'] == 'final_epoch', 'Final epoch selection required')
    return effective


def build_plan(protocol_path, config_path, root=ROOT):
    protocol = yaml.safe_load(protocol_path.read_text())
    config = yaml.safe_load(config_path.read_text())
    index_path = root / protocol['training']['full_train_index']
    index = json.loads(index_path.read_text())
    validate_index(index, protocol)
    blockers = release_blockers(protocol, root)
    # Validate parameter registration even while release gates remain closed.
    try:
        validate_formal_config(config, protocol, root, 'T1', config['dialogues'],
                               config['sequence_length'], config['scheduler_steps'])
    except ValueError as error:
        if not str(error).startswith('Formal training blocked:'):
            raise
    checkpoints = list(range(config['save_every_steps'], config['scheduler_steps'], config['save_every_steps']))
    checkpoints.append(config['scheduler_steps'])
    inventory = root / protocol['assets']['verified_inventory']
    conditions = {'B0': {'updates': False, 'initialization': 'complete_official_checkpoint',
                          'checkpoint_steps': [0], 'evaluation_checkpoint_step': 0,
                          'test_input': 'frozen_prior_fdb_audio_native_asr'}}
    for arm in ARMS:
        conditions[arm] = {'updates': True, 'initialization': 'complete_official_checkpoint',
                           'index': index[arm], 'checkpoint_steps': checkpoints,
                           'evaluation_checkpoint_step': config['scheduler_steps'],
                           'intermediate_checkpoint_role': 'recovery_and_debug_only',
                           'test_input': 'frozen_prior_fdb_audio_native_asr',
                           'max_gpu_hours': protocol['training']['max_gpu_hours_per_condition'][0]}
    return {'schema_version': 1, 'issue': '006', 'training_released': not blockers,
            'blockers': blockers, 'conditions': conditions, 'training_config': config,
            'inputs': {str(path.relative_to(root) if path.is_relative_to(root) else path): sha256_file(path) for path in
                       (protocol_path, config_path, index_path, inventory)},
            'assets': protocol['assets'], 'data': protocol['data'],
            'runtime': protocol['runtime'], 'post_training_evaluation': protocol['post_training_evaluation'],
            'selection': 'fixed final epoch; each model generates its own history; no test-based checkpoint selection',
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
