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


def score_predictions(rows, predictions):
    predictions = {p['snapshot_id']: p for p in predictions}
    groups = defaultdict(list)
    for row in rows:
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
        opportunities.append({'opportunity_id': identity, 'source_id': windows[0]['source_id'],
                              'category': category, 'declarative': any(r.get('utterance_form') == 'declarative' for r in anchors),
                              'success': success, 'false_action': false_action, 'missing': missing,
                              'timely': timely if action else None, 'windows': len(windows)})
    result = {}
    for name, category in [('smooth', 'smooth'), ('declarative', 'smooth'), ('interruption', 'interruption'),
                           ('pause_false_start', 'pause'), ('backchannel_false_stop', 'backchannel')]:
        selected = [r for r in opportunities if r['category'] == category and
                    (name != 'declarative' or r['declarative'])]
        negative = name in ('pause_false_start', 'backchannel_false_stop')
        numerator = sum((not r['success']) if negative else r['success'] for r in selected)
        result[name] = metric(numerator, len(selected))
    durations = sorted(p['control_ms'] for p in predictions.values() if p.get('control_ms') is not None)
    successes = sum(predictions.get(r['snapshot_id'], {}).get('action') is not None for r in rows)
    result['runtime'] = metric(successes, len(rows))
    result['control_ms_p95'] = durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None
    result['opportunity_score'] = sum(
        result[name]['rate'] if name not in ('pause_false_start', 'backchannel_false_stop')
        else 1 - result[name]['rate']
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
                                                    'success', 'false_action', 'missing', 'timely', 'windows'])
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
