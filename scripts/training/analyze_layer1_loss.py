"""Analyze recorded optimizer losses and target frequencies without loading a model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


CONTROL_WEIGHTS = {'speaking': 1, 'finish': 10, 'interruption': 5, 'backchannel': 2, 'thinking': 1}


def aggregate(rows):
    tokens = sum(row['effective_tokens'] for row in rows)
    return {'start_step': rows[0]['step'], 'end_step': rows[-1]['step'], 'steps': len(rows),
            'effective_tokens': tokens, 'loss_step_mean': statistics.mean(row['loss'] for row in rows),
            'loss_token_mean': sum(row['loss'] * row['effective_tokens'] for row in rows) / tokens,
            'loss_min': min(row['loss'] for row in rows), 'loss_max': max(row['loss'] for row in rows),
            'grad_norm_mean_before_clipping': statistics.mean(row['grad_norm'] for row in rows),
            'grad_norm_max_before_clipping': max(row['grad_norm'] for row in rows),
            'fraction_grad_norm_above_one': sum(row['grad_norm'] > 1 for row in rows) / len(rows),
            'mean_step_seconds': statistics.mean(row['seconds'] for row in rows)}


def class_mass(observation):
    counts = {'body': observation['target_counts']['body'], 'eos': observation['target_counts']['eos']}
    counts.update({name: observation['controls'][name] for name in CONTROL_WEIGHTS})
    total = sum(counts.values())
    assert total == observation['target_counts']['total']
    weighted_total = sum(count * CONTROL_WEIGHTS.get(name, 1) for name, count in counts.items())
    return {'unweighted_total': total, 'candidate_weighted_total': weighted_total,
            'classes': {name: {'count': count, 'token_fraction': count / total,
                               'candidate_weight': CONTROL_WEIGHTS.get(name, 1),
                               'candidate_nominal_weight_fraction': count * CONTROL_WEIGHTS.get(name, 1) / weighted_total}
                        for name, count in counts.items()},
            'interpretation': 'Target counts and nominal objective mass; not measured per-class loss or gradient.'}


def analyze(observation):
    rows = [dict(zip(observation['step_fields'], values)) for values in observation['steps']]
    assert rows and [row['step'] for row in rows] == list(range(1, len(rows) + 1))
    assert all(math.isfinite(row['loss']) and row['loss'] >= 0 and
               math.isfinite(row['grad_norm']) and row['grad_norm'] > 0 and
               row['effective_tokens'] > 0 for row in rows)
    total_tokens = sum(row['effective_tokens'] for row in rows)
    assert total_tokens == observation['target_counts']['total']
    summary = observation['t1_summary']
    assert summary and summary['passed'] and observation['t1_exit_code'] == '0'
    assert summary['final_step'] == len(rows) and summary['cursor'] == len(rows) * 2
    first, last = aggregate(rows[:100]), aggregate(rows[-100:])
    report = {'observed_at': observation['observed_at'], 't1_execution_passed': True,
              'steps_source_sha256': observation['steps_sha256'], 'all': aggregate(rows),
              'first100': first, 'last100': last,
              'first_to_last100_token_loss_relative_change': last['loss_token_mean'] / first['loss_token_mean'] - 1,
              'windows100': [aggregate(rows[start:start + 100]) for start in range(0, len(rows), 100)],
              'last_step': rows[-1], 'supervision': class_mass(observation),
              'missing_evidence': ['per-class model NLL', 'per-class recall and confusion',
                                   'paired B0/T1 behavior on the fixed FDB subset'],
              'training_configuration_changed': False}
    return rows, report


def plot(rows, report, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    steps = np.array([row['step'] for row in rows])
    losses = np.array([row['loss'] for row in rows])
    tokens = np.array([row['effective_tokens'] for row in rows])
    numerator = np.convolve(losses * tokens, np.ones(50), mode='valid')
    denominator = np.convolve(tokens, np.ones(50), mode='valid')
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True)
    ax = axes[0]
    ax.plot(steps, losses, color='#aeb8c4', alpha=0.55, linewidth=0.65, label='Per-step training loss')
    ax.plot(steps[49:], numerator / denominator, color='#1764a0', linewidth=2,
            label='50-step token-weighted mean')
    ax.set(xlabel='Optimizer step', ylabel='Unweighted token cross-entropy', title='T1: one epoch, original user punctuation')
    ax.grid(alpha=0.2)
    ax.legend(loc='upper right')
    lr = ax.twinx()
    lr.plot(steps, [row['learning_rate'] for row in rows], color='#ba6a25', alpha=0.65,
            linestyle='--', label='Learning rate')
    lr.set_ylabel('Learning rate')
    lr.ticklabel_format(axis='y', style='sci', scilimits=(0, 0))
    lr.legend(loc='lower right')
    names = list(CONTROL_WEIGHTS)
    labels = ['Talking', 'Handover', 'Interruption', 'Backchannel', 'Thinking']
    counts = [report['supervision']['classes'][name]['count'] for name in names]
    axes[1].bar(labels, counts, color=['#627c9c', '#c17d27', '#ba4c4c', '#8d659c', '#579880'])
    for index, count in enumerate(counts):
        fraction = report['supervision']['classes'][names[index]]['token_fraction']
        axes[1].text(index, count + 500, f'{count:,}\n{fraction:.3%} of targets', ha='center', va='bottom', fontsize=9)
    axes[1].set(ylabel='Supervised control-token count', title='Train-only targets; body and EOS excluded from bars')
    axes[1].set_ylim(0, max(counts) * 1.2)
    axes[1].grid(axis='y', alpha=0.2)
    fig.savefig(output / 'loss_curve.png', dpi=180)
    fig.savefig(output / 'loss_curve.pdf')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    observation = json.loads(args.input.read_text())
    rows, report = analyze(observation)
    report['observation_sha256'] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    with (args.output / 'steps.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=observation['step_fields'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    plot(rows, report, args.output)
    print(json.dumps({'first100': report['first100'], 'last100': report['last100'],
                      'relative_change': report['first_to_last100_token_loss_relative_change'],
                      'supervision': report['supervision']}, indent=2))


if __name__ == '__main__':
    main()
