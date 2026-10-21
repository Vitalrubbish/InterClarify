"""Audit a completed single epoch and aggregate token-weighted loss diagnostics."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics

from layer1_data import file_digest, write_json
from layer1_loss import CONTROL_WEIGHTS


def aggregate(rows):
    """Aggregate sufficient statistics, avoiding averages of unequal batches."""
    tokens = sum(r['effective_tokens'] for r in rows)
    denominator = sum(r['target_weight_sum'] for r in rows)
    ordinary_sum = sum(r['ordinary_ce'] * r['effective_tokens'] for r in rows)
    weighted_sum = sum(r['weighted_objective'] * r['target_weight_sum'] for r in rows)
    controls = {}
    for name, weight in CONTROL_WEIGHTS.items():
        count = sum(r['control_targets'][name]['count'] for r in rows)
        nll_sum = sum((r['control_targets'][name]['mean_nll'] or 0) * r['control_targets'][name]['count'] for r in rows)
        controls[name] = {'count': count, 'mean_nll': nll_sum / count if count else None,
                          'nll_sum': nll_sum, 'weighted_nll_share': weight * nll_sum / weighted_sum,
                          'weighted_target_share': count * weight / denominator}
    remaining_count = tokens - sum(c['count'] for c in controls.values())
    remaining_sum = ordinary_sum - sum(c['nll_sum'] for c in controls.values())
    return {'step_start': rows[0]['step'], 'step_end': rows[-1]['step'], 'steps': len(rows),
            'tokens': tokens, 'target_weight_sum': denominator,
            'weighted_ce': weighted_sum / denominator, 'ordinary_ce': ordinary_sum / tokens,
            'step_loss_mean': statistics.mean(r['loss'] for r in rows), 'controls': controls,
            'body_and_eos': {'count': remaining_count, 'mean_nll': remaining_sum / remaining_count,
                             'weighted_nll_share': remaining_sum / weighted_sum}}


def summarize(rows):
    losses = sorted(r['loss'] for r in rows)
    gradients = sorted(r['grad_norm'] for r in rows)

    def quantile(values, fraction):
        offset = (len(values) - 1) * fraction
        left = math.floor(offset)
        return values[left] + (values[min(left + 1, len(values) - 1)] - values[left]) * (offset - left)

    return {'all': aggregate(rows), 'first_100': aggregate(rows[:100]), 'last_100': aggregate(rows[-100:]),
            'quarters': [aggregate(rows[i * len(rows) // 4:(i + 1) * len(rows) // 4]) for i in range(4)],
            'bins_50': [aggregate(rows[i:i + 50]) for i in range(0, len(rows), 50)],
            'last_step': {k: rows[-1][k] for k in ('step', 'loss', 'ordinary_ce', 'grad_norm', 'learning_rate')},
            'loss_distribution': {str(q): quantile(losses, q) for q in (0, 0.05, 0.5, 0.95, 1)},
            'gradient_pre_clip': {'max': max(gradients), 'median': quantile(gradients, 0.5),
                                  'p95': quantile(gradients, 0.95),
                                  'steps_over_one': sum(g > 1 for g in gradients)},
            'largest_loss_steps': [{k: r[k] for k in ('step', 'loss', 'ordinary_ce', 'effective_tokens')}
                                   for r in sorted(rows, key=lambda r: r['loss'], reverse=True)[:5]]}


def analyze(run):
    """Require completed training and reload before reporting success."""
    training = run / 'training'
    summary = json.loads((training / 'summary.json').read_text())
    manifest = json.loads((training / 'manifest.json').read_text())
    reload = json.loads((run / 'candidate_reload.json').read_text())
    rows = [json.loads(line) for line in (training / 'steps.jsonl').read_text().splitlines()]
    config = manifest['identity']['config']
    ids = []
    cursor = 0
    max_residual = 0.0
    for step, row in enumerate(rows, 1):
        assert row['step'] == step
        ids.extend(row['sequence_ids'])
        cursor += len(row['sequence_ids'])
        assert row['cursor'] == cursor
        assert all(math.isfinite(row[k]) for k in ('loss', 'ordinary_ce', 'grad_norm', 'target_weight_sum'))
        assert row['loss'] == row['weighted_objective'] and row['grad_norm'] > 0
        ordinary = row['ordinary_ce'] * row['effective_tokens']
        adjustment = sum((CONTROL_WEIGHTS[n] - 1) * c['count'] * (c['mean_nll'] or 0)
                         for n, c in row['control_targets'].items())
        expected_weight = row['effective_tokens'] + sum((CONTROL_WEIGHTS[n] - 1) * c['count']
                                                       for n, c in row['control_targets'].items())
        assert row['target_weight_sum'] == expected_weight
        residual = abs((ordinary + adjustment) / expected_weight - row['loss'])
        assert residual < 1e-5, 'Weighted objective disagrees with control diagnostics'
        max_residual = max(max_residual, residual)
    assert len(rows) == summary['final_step'] == config['scheduler_steps'] == 1240
    assert len(ids) == len(set(ids)) == summary['cursor'] == summary['exposed_sequences'] == 2480
    assert len({s.rsplit(':', 3)[0] for s in ids}) == summary['exposed_dialogues'] == 1000
    assert sum(r['effective_tokens'] for r in rows) == summary['data_statistics']['effective_tokens'] == 1201531
    assert summary['passed'] and summary['frozen_tensors_unchanged'] and len(summary['changed_tensors']) == 112
    checkpoint_sha = file_digest(training / 'checkpoint.pt')
    assert checkpoint_sha == summary['checkpoint']['sha256'] == reload['checkpoint_sha256']
    assert reload['inference_eligible'] and reload['clean_process_probe_ids_match']
    assert reload['complete_inference_weights_match_training']
    assert int((run / 'exit_code.txt').read_text()) == 0
    assert not (training / 'failure.json').exists()
    control_counts = Counter({name: sum(r['control_targets'][name]['count'] for r in rows) for name in CONTROL_WEIGHTS})
    return {'schema_version': 1, 'condition': config['condition'], 'checks_passed': True,
            'coverage': {'steps': len(rows), 'sequences': len(ids), 'unique_sequences': len(set(ids)),
                         'dialogues': 1000, 'tokens': 1201531, 'control_counts': control_counts},
            'max_weighted_objective_residual': max_residual, 'loss': summarize(rows),
            'run': str(run), 'checkpoint_sha256': checkpoint_sha,
            'elapsed_seconds': summary['total_seconds'], 'loop_seconds': summary['loop_seconds'],
            'peak_allocated_bytes': summary['peak_allocated_bytes'],
            'peak_reserved_bytes': summary['peak_reserved_bytes'], 'max_rss_kib': summary['max_rss_kib'],
            'output_bytes': sum(p.stat().st_size for p in run.rglob('*') if p.is_file()),
            'sources': {str(p.relative_to(run)): file_digest(p) for p in (training / 'steps.jsonl',
                training / 'summary.json', training / 'manifest.json', run / 'candidate_reload.json', run / 'exit_code.txt')},
            'analyzer_sha256': file_digest(__file__), 'validation_loss_available': False,
            'fdb_evaluation_performed': False, 'old_loss_trace_available': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = analyze(args.run)
    write_json(args.output, report)
    print(json.dumps({'checks_passed': report['checks_passed'], 'coverage': report['coverage']}))
