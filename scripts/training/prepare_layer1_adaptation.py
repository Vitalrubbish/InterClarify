"""Validate the frozen delayed-start configuration, data audit and training index."""

from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

from layer1_model import sha256_file


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_DELAYED_CONFIG = {
    'schema_version': 1,
    'purpose': 'issue040_delayed_start',
    'seed': 20261020,
    'dialogues': 1000,
    'sequence_length': 2048,
    'learning_rate': 2.0e-05,
    'weight_decay': 0.01,
    'adam_betas': [0.9, 0.999],
    'adam_eps': 1.0e-08,
    'gradient_accumulation': 2,
    'batch_size': 1,
    'max_grad_norm': 1.0,
    'scheduler_steps': 1235,
    'warmup_steps': 124,
    'save_every_steps': 206,
    'max_wall_seconds': 28800,
    'gradient_checkpointing': True,
    'deterministic': True,
    'max_output_gib': 5,
    'min_free_gib': 5,
    'condition': 'T2_R3_delayed_start',
    'loss': {
        'type': 'control_weighted_ce',
        'control_weights': {'speaking': 1, 'finish': 10, 'interruption': 5,
                            'backchannel': 2, 'thinking': 1},
        'chunk_size': 64,
    },
}


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


def validate_index(index, protocol):
    """Check the frozen T2 index used by the final delayed-start epoch."""
    require('T2' in index and index['T2'].get('arm') == 'T2', 'Missing T2 training index')
    row = index['T2']
    training = protocol['training']
    require(len(row['subset']) == len(set(row['subset'])) == 1000, 'Duplicate/missing train dialogues')
    require(row['length'] == training['sequence_length'], 'Index window mismatch')
    stats = row['statistics']
    require(stats['sequences'] == training['round1_sequences_per_condition'], 'Sequence count mismatch')
    require(stats['effective_tokens'] == training['round1_effective_tokens_per_condition'],
            'Supervision budget mismatch')
    require(math.ceil(stats['sequences'] / training['effective_batch']) == training['actual_steps'],
            'Optimizer step budget mismatch')


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
    require(config == EXPECTED_DELAYED_CONFIG and config['condition'] == protocol['condition'],
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
            and audit['response_start_timing'] == 'next_no_voice',
            'Latest delayed dataset audit changed')
    index_path = root / protocol['training']['full_train_index']
    require(protocol.get('full_train_index_sha256') and
            sha256_file(index_path) == protocol['full_train_index_sha256'], 'Delayed full index changed')
    index = json.loads(index_path.read_text())
    effective = {**parent, 'training': {**parent['training'], **protocol['training']},
                 'post_training_evaluation': {**parent['post_training_evaluation'],
                     'conditions': ['T2_R3_delayed_start'], 'automatic_submit': False}}
    validate_index(index, effective)
    for row in index.values():
        require(row['manifest_sha256'] == protocol['data_manifest_sha256']
                and row['audit_sha256'] == protocol['data_audit_sha256'], 'Index uses an older dataset')
    require(effective['training']['checkpoint_selection'] == 'final_epoch', 'Final epoch selection required')
    return effective
