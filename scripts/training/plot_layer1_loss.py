"""Export standalone training-loss charts from verified aggregate diagnostics."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def plot(source, output):
    report = json.loads(source.read_text())
    bins = report['loss']['bins_50']
    x = [(r['step_start'] + r['step_end']) / 2 for r in bins]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3), layout='constrained')
    axes[0].plot(x, [r['weighted_ce'] for r in bins], label='Weighted CE', linewidth=2)
    axes[0].plot(x, [r['ordinary_ce'] for r in bins], label='Ordinary CE', linewidth=2)
    axes[0].plot(x, [r['body_and_eos']['mean_nll'] for r in bins], label='Body + EOS NLL', linestyle='--')
    axes[0].set(title='Training objective (50-step aggregates)', ylabel='Token-weighted mean NLL')
    for name in ('speaking', 'finish', 'interruption', 'backchannel', 'thinking'):
        axes[1].plot(x, [r['controls'][name]['mean_nll'] for r in bins], label=name, linewidth=1.7)
    axes[1].set(title='Control targets (count-weighted NLL)', ylabel='Mean NLL, logarithmic scale', yscale='log')
    for ax in axes:
        ax.axvline(124, color='#666666', linewidth=1, linestyle=':', label='Warmup end' if ax is axes[0] else None)
        ax.set_xlabel('Optimizer step')
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
    fig.suptitle('ASR_R4_delayed_punctuation: original 1k, one epoch; training data only', fontsize=12)
    for suffix in ('.png', '.svg'):
        fig.savefig(output.with_suffix(suffix), dpi=180)
    svg = output.with_suffix('.svg')
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plot(args.input, args.output)
