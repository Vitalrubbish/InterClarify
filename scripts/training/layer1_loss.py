"""Compute causal control-weighted CE with bounded recomputed vocabulary chunks."""

from collections import Counter


CONTROL_TOKENS = {
    'speaking': '<|user is talking|>',
    'finish': '<|user finish talking|>',
    'interruption': '<|user interruption|>',
    'backchannel': '<|user backchannel|>',
    'thinking': '<|user is thinking|>',
}
CONTROL_WEIGHTS = dict(speaking=1, finish=10, interruption=5, backchannel=2, thinking=1)


def target_statistics(rows, token_ids, weights):
    """Count shifted effective targets before splitting an accumulation batch."""
    counts = Counter(token for row in rows for token in row['labels'][1:] if token != -100)
    categories = {name: counts[token_ids[token]] for name, token in CONTROL_TOKENS.items()}
    total = sum(counts.values())
    if not total:
        raise ValueError('No effective causal targets')
    return {'effective_tokens': total, 'target_weight_sum': total + sum(
        categories[name] * (weights[name] - 1) for name in CONTROL_TOKENS),
        'control_counts': categories}


def weighted_causal_loss(logits, labels, token_ids, weights, chunk_size=64):
    """Return the weighted numerator and detached sufficient diagnostics."""
    import torch
    from torch.nn import functional as F
    from torch.utils.checkpoint import checkpoint

    if logits.shape[:2] != labels.shape or labels.shape[1] < 2 or chunk_size < 1:
        raise ValueError('Invalid causal loss dimensions or chunk size')
    targets = labels[:, 1:]
    valid = targets != -100
    count = int(valid.sum())
    if not count:
        raise ValueError('No effective causal targets')
    target_weights = valid.to(torch.float32)
    masks = {name: valid & (targets == token_ids[token]) for name, token in CONTROL_TOKENS.items()}
    for name, mask in masks.items():
        target_weights = target_weights + mask * (weights[name] - 1)

    def token_ce(block, target):
        return F.cross_entropy(block.float().reshape(-1, block.shape[-1]), target.reshape(-1),
                               ignore_index=-100, reduction='none').reshape(target.shape)

    numerator = logits.new_zeros((), dtype=torch.float32)
    ordinary = numerator.detach().clone()
    nll = {name: ordinary.clone() for name in CONTROL_TOKENS}
    for start in range(0, targets.shape[1], chunk_size):
        end = min(start + chunk_size, targets.shape[1])
        block, target = logits[:, start:end, :], targets[:, start:end]
        ce = checkpoint(token_ce, block, target, use_reentrant=False, preserve_rng_state=False)
        numerator = numerator + (ce * target_weights[:, start:end]).sum()
        ordinary = ordinary + ce.detach().sum()
        for name in CONTROL_TOKENS:
            nll[name] = nll[name] + (ce.detach() * masks[name][:, start:end]).sum()
    diagnostics = {'ordinary_nll_sum': float(ordinary), 'effective_tokens': count,
                   'target_weight_sum': float(target_weights.sum()),
                   'control_counts': {name: int(mask.sum()) for name, mask in masks.items()},
                   'control_nll_sums': {name: float(value) for name, value in nll.items()}}
    return numerator, diagnostics
