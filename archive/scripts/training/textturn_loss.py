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


def stage_loss_weights(rows, policy=None):
    """Balance action mass using stage-wide constants without changing frozen row weights."""
    base = weight_summary(rows)
    if policy is None:
        return [r['loss_weight'] for r in rows], base
    shares = policy.get('action_shares', {})
    actions = {'keep', 'start', 'stop'}
    if (policy.get('method') != 'stage_action_mass' or set(shares) != actions or
            any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in shares.values()) or
            not math.isclose(math.fsum(shares.values()), 1., abs_tol=1e-12, rel_tol=0)):
        raise ValueError('Use three positive action shares summing to one')
    masses = base['action_weight_mass']
    if set(masses) != actions:
        raise ValueError('Stage action balancing requires keep, start and stop examples')
    n = len(rows)
    factors = {a: n * shares[a] / masses[a] for a in shares}
    weights = [r['loss_weight'] * factors[r['target_action']] for r in rows]
    if any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError('Every effective weight must be finite and positive')
    effective = {a: math.fsum(w for r, w in zip(rows, weights) if r['target_action'] == a) for a in shares}
    return weights, {'snapshots': n, 'method': policy['method'], 'base_weights': base,
                     'action_shares': dict(shares), 'action_scale_factors': factors,
                     'raw_weight_sum': math.fsum(weights), 'mean_weight': 1.,
                     'action_weight_mass': effective, 'min_weight': min(weights), 'max_weight': max(weights)}


def weighted_action_loss(logits, targets, weights, mean_weight):
    import torch
    if not math.isfinite(mean_weight) or mean_weight <= 0:
        raise ValueError('Use a fixed positive stage-wide normalization constant')
    losses = torch.nn.functional.cross_entropy(logits, targets, reduction='none')
    weights = torch.as_tensor(weights, device=losses.device, dtype=losses.dtype)
    if weights.shape != losses.shape or not torch.isfinite(weights).all() or not (weights > 0).all():
        raise ValueError('One finite positive weight is required per target')
    return (losses * weights).sum() / (losses.numel() * mean_weight)


def logical_groups(rows):
    """Combine complete same-source, same-form trajectories before one optimizer step."""
    complete_trajectory_groups(rows)
    grouped = defaultdict(list)
    for row in rows:
        key = (row['source_id'], row.get('logical_group', row.get('utterance_form')))
        grouped[key].append(row)
    result = []
    for key, windows in sorted(grouped.items()):
        masses = {a: math.fsum(r['loss_weight'] for r in windows if r['target_action'] == a)
                  for a in ('keep', 'start', 'stop')}
        if any(not math.isfinite(v) or v <= 0 for v in masses.values()):
            raise ValueError(f'Logical group lacks a positive action mass: {key}')
        scales = [r['loss_weight'] / (3 * masses[r['target_action']]) for r in windows]
        if any(not math.isfinite(w) or w <= 0 for w in scales):
            raise ValueError('Logical group requires finite positive weights')
        result.append((key, windows, scales))
    return result
