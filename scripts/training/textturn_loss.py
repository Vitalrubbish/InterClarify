"""Weight every causal window while bounding repeated keep exposure."""
from collections import Counter, defaultdict
import math
import random


def assign_loss_weights(rows, policy):
    keep_counts = Counter((r['scenario_id'], r['visible']['state'], r['category'])
                          for r in rows if r['target_action'] == 'keep')
    for row in rows:
        action = row['target_action']
        if action == 'keep':
            count = keep_counts[(row['scenario_id'], row['visible']['state'], row['category'])]
            weight = min(1., policy['keep_group_budget'] / count)
        else:
            weight = policy['action_weights'][action]
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError('Every supervised window must have a finite positive weight')
        row['loss_weight'] = weight
    return rows


def complete_trajectory_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['scenario_id']].append(row)
    for identity, windows in groups.items():
        positions = [int(r['snapshot_id'].rsplit(':', 1)[1]) for r in windows]
        if positions != list(range(len(windows))):
            raise ValueError(f'Trajectory contains missing, reordered or duplicate windows: {identity}')
        times = [r['visible_ms'] for r in windows]
        if times != sorted(times) or len(set(times)) != len(times):
            raise ValueError(f'Trajectory clock is not strictly increasing: {identity}')
        if any(r['excluded_reason'] for r in windows):
            raise ValueError('A complete trajectory cannot contain excluded windows')
    return list(groups.values())


def trajectory_order(rows, seed):
    groups = complete_trajectory_groups(rows)
    random.Random(seed).shuffle(groups)
    return [row for group in groups for row in group]


def weight_summary(rows):
    masses = defaultdict(float)
    for row in rows:
        weight = row['loss_weight']
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError('Invalid loss weight')
        masses[row['target_action']] += weight
    total = math.fsum(r['loss_weight'] for r in rows)
    if not rows:
        raise ValueError('Cannot normalize an empty dataset')
    return {'snapshots': len(rows), 'raw_weight_sum': total, 'mean_weight': total / len(rows),
            'action_weight_mass': dict(masses),
            'min_weight': min(r['loss_weight'] for r in rows),
            'max_weight': max(r['loss_weight'] for r in rows)}


def weighted_action_loss(logits, targets, weights, mean_weight):
    import torch
    if not math.isfinite(mean_weight) or mean_weight <= 0:
        raise ValueError('Use a fixed positive stage-wide normalization constant')
    losses = torch.nn.functional.cross_entropy(logits, targets, reduction='none')
    weights = torch.as_tensor(weights, device=losses.device, dtype=losses.dtype)
    if weights.shape != losses.shape or not torch.isfinite(weights).all() or not (weights > 0).all():
        raise ValueError('One finite positive weight is required per target')
    return (losses * weights).sum() / (losses.numel() * mean_weight)
