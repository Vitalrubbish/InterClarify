"""Score complete TextTurn opportunities without rewarding repeated keep frames."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path


def wilson(numerator, denominator):
    if not denominator:
        return [None, None]
    p, z = numerator / denominator, 1.959963984540054
    divisor = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / divisor
    radius = z * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator**2)) / divisor
    return [max(0., center - radius), min(1., center + radius)]


def metric(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None,
            'wilson_95': wilson(numerator, denominator)}


def outcome_metric(opportunities, negative=False):
    """Keep missing evidence separate from observed action errors and success."""
    total = len(opportunities)
    passed = sum(r['outcome'] == 'pass' for r in opportunities)
    failed = sum(r['outcome'] == 'fail' for r in opportunities)
    unknown = total - passed - failed
    known = passed + failed
    errors = sum(bool(r.get('actual_error')) for r in opportunities)
    numerator = errors if negative else passed
    denominator = known if negative else total
    result = metric(numerator, denominator)
    result.update(planned=total, passed=passed, failed=failed, unknown=unknown,
                  actual_errors=errors, adjudicated=known,
                  adjudicated_coverage=known / total if total else None,
                  conditional_success=metric(passed, known),
                  planned_success_bounds=[passed / total, (passed + unknown) / total] if total else [None, None],
                  planned_error_bounds=[errors / total, (errors + unknown) / total] if total else [None, None])
    return result


def score_predictions(rows, predictions):
    predictions = {p['snapshot_id']: p for p in predictions}
    groups = defaultdict(list)
    first_starts = {}
    for row in rows:
        if row.get('scenario_variant') and row['target_action'] == 'start':
            identity = row['scenario_id']
            first_starts[identity] = min(row['visible_ms'], first_starts.get(identity, math.inf))
    for row in rows:
        if (row.get('scenario_variant') and row['category'] in ('listen', 'inter_chunk_gap')
                and row['visible']['state'] == 'Listen'
                and row['visible_ms'] < first_starts.get(row['scenario_id'], -math.inf)):
            row = row | {'category': 'smooth', 'opportunity_id': f"{row['scenario_id']}:smooth"}
        if row['category'] in ('smooth', 'pause', 'backchannel', 'interruption'):
            groups[row['opportunity_id']].append(row)
    opportunities = []
    for identity, windows in groups.items():
        category = windows[0]['category']
        action = {'smooth': 'start', 'interruption': 'stop'}.get(category)
        missing = any(predictions.get(r['snapshot_id'], {}).get('action') is None for r in windows)
        false_action = any(r['target_action'] == 'keep' and
                           predictions.get(r['snapshot_id'], {}).get('action') not in (None, 'keep') for r in windows)
        anchors = [r for r in windows if r['target_action'] == action] if action else []
        timely = False
        for anchor in anchors:
            prediction = predictions.get(anchor['snapshot_id'], {})
            elapsed = prediction.get('control_ms')
            if prediction.get('action') == action and elapsed is not None:
                timely |= anchor['visible_ms'] - anchor['allowed_visible_ms'] + elapsed <= 1000
        success = not missing and not false_action and (timely if action else True)
        outcome = 'fail' if false_action else 'unknown' if missing else 'pass' if success else 'fail'
        opportunities.append({'opportunity_id': identity, 'source_id': windows[0]['source_id'],
                              'category': category, 'declarative': any(r.get('utterance_form') == 'declarative' for r in anchors),
                              'success': success, 'outcome': outcome, 'actual_error': false_action,
                              'false_action': false_action, 'missing': missing,
                              'timely': timely if action else None, 'windows': len(windows)})
    result = {}
    for name, category in [('smooth', 'smooth'), ('declarative', 'smooth'), ('interruption', 'interruption'),
                           ('pause_false_start', 'pause'), ('backchannel_false_stop', 'backchannel')]:
        selected = [r for r in opportunities if r['category'] == category and
                    (name != 'declarative' or r['declarative'])]
        negative = name in ('pause_false_start', 'backchannel_false_stop')
        result[name] = outcome_metric(selected, negative=negative)
    durations = sorted(p['control_ms'] for p in predictions.values() if p.get('control_ms') is not None)
    successes = sum(predictions.get(r['snapshot_id'], {}).get('action') is not None for r in rows)
    result['runtime'] = metric(successes, len(rows))
    result['control_ms_p95'] = durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None
    result['opportunity_score'] = sum(
        result[name]['rate'] if name not in ('pause_false_start', 'backchannel_false_stop')
        else 1 - result[name]['planned_error_bounds'][1]
        for name in ('smooth', 'declarative', 'interruption', 'pause_false_start', 'backchannel_false_stop')
        if result[name]['rate'] is not None) / 5
    result['evaluation_mode'] = 'offline_given_state_text_diagnostic'
    result['online_pass'] = None
    return result, opportunities


def score_file(rows, predictions, output):
    result, opportunities = score_predictions(rows, predictions)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with (output / 'opportunities.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['opportunity_id', 'source_id', 'category', 'declarative',
                                                    'success', 'outcome', 'actual_error', 'false_action',
                                                    'missing', 'timely', 'windows'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(opportunities)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    read = lambda path: [json.loads(line) for line in path.open()]
    print(json.dumps(score_file(read(args.data), read(args.predictions), args.output), indent=2))
