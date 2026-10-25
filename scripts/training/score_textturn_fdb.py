"""Score ASR-boundary controller actions without loading a response model or reference text."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics


def percentile(values, q=.95):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    lo = int(position)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (position - lo)


def proportion(values, planned=50):
    hit = sum(v is True for v in values)
    miss = sum(v is False for v in values)
    unknown = planned - hit - miss
    if unknown < 0:
        raise ValueError('Observed more than planned')
    n, z = hit + miss, 1.959963984540054
    interval = None
    if n:
        center = (hit / n + z*z / (2*n)) / (1 + z*z/n)
        half = z * math.sqrt(hit/n * (1-hit/n)/n + z*z/(4*n*n)) / (1+z*z/n)
        interval = [max(0., center-half), min(1., center+half)]
    return {'hit': hit, 'confirmed_miss': miss, 'unknown': unknown, 'planned': planned,
            'conservative_bounds': [hit/planned, (hit+unknown)/planned],
            'decidable_numerator': hit, 'decidable_denominator': n,
            'decidable_rate': hit/n if n else None, 'wilson95': interval}


def score_case(case, events, control_ms=480):
    if control_ms not in (160, 480):
        raise ValueError('Unsupported control period')
    steps_per_window = control_ms // 160
    row = {'case_id': case['case_id'], 'subset': case['subset'], 'sample_id': case['sample_id'],
           'control_ms': control_ms, 'start_wait_ms': None,
           't_last_asr_update': None, 'post_asr_speak': None, 'post_asr_start': None,
           'first_post_asr_start_at': None, 'start_wait_beats': None,
           'start_timing_unknown': False, 'pre_asr_three_speak': None,
           'longest_pre_asr_speak': None, 'speak_sequences': [], 'unknown_reason': None}
    ends = [e for e in events if e['kind'] == 'case_end']
    starts = [e for e in events if e['kind'] == 'case_start']
    if len(starts) != 1 or starts[0].get('controller_state_mode') != 'action_only':
        row['unknown_reason'] = 'missing_action_only_protocol_or_retired_trace'
        return row
    if any(e.get('control_ms', 480) != control_ms for e in events if e['kind'] == 'case_start'):
        row['unknown_reason'] = 'control_period_mismatch'
        return row
    updates, previous = [], ''
    for event in events:
        if event['kind'] == 'context_publish' and event['text'] != previous:
            if event['text'].strip():
                updates.append(event)
            previous = event['text']
    if len(ends) != 1 or not ends[0]['runtime_success']:
        row['unknown_reason'] = 'runtime_failed_or_incomplete_trace'
        return row
    if not updates:
        row['unknown_reason'] = 'no_valid_online_asr_transcript'
        return row
    boundary = updates[-1]['published_at']
    row['t_last_asr_update'] = boundary
    actions = [e for e in events if e['kind'] == 'control_result']
    windows = [e for e in events if e['kind'] == 'control_window']
    if (not actions or len(actions) != ends[0]['control_calls'] or
            any(e.get('error') or e.get('state_after') not in ('Listen', 'Speak') or
                e.get('state_recorded_at') is None or e.get('action_returned_at') is None
                for e in actions)):
        row['unknown_reason'] = 'missing_or_failed_control_trace'
        return row
    # A merged request covers its sequence range once, never as several observed cycles.
    covered = sum(e['window']['step_count'] // steps_per_window for e in actions)
    if covered != len(windows) or any(e['window'].get('partial_window') for e in actions):
        row['unknown_reason'] = 'missing_complete_window_results'
        return row
    row.update(post_asr_speak=False, post_asr_start=False, pre_asr_three_speak=False,
               longest_pre_asr_speak=0)
    ordered = sorted(actions, key=lambda e: e['state_recorded_at'])
    streak, first, last_step = 0, None, None
    sequences = []
    for event in ordered:
        window, at = event['window'], event['state_recorded_at']
        if at > boundary and event['state_after'] == 'Speak':
            row['post_asr_speak'] = True
        if event['action'] == 'start' and event['action_returned_at'] > boundary:
            row['post_asr_start'] = True
            if row['first_post_asr_start_at'] is None:
                row['first_post_asr_start_at'] = event['action_returned_at']
                row['start_wait_ms'] = (event['action_returned_at'] - boundary) * 1000
                row['start_wait_beats'] = row['start_wait_ms'] / control_ms
        gap = (last_step is not None and window['first_step_seq'] != last_step + 1) or window['step_count'] != steps_per_window
        if gap:
            streak, first = 0, None
        if at < boundary and event['state_after'] == 'Speak':
            streak += 1
            first = at if first is None else first
            row['longest_pre_asr_speak'] = max(row['longest_pre_asr_speak'], streak)
            if streak >= 3:
                row['pre_asr_three_speak'] = True
                sequences.append({'first_at': first, 'last_at': at, 'cycles': streak})
        else:
            streak, first = 0, None
        last_step = window['last_step_seq']
    # Preserve maximal runs rather than repeated prefixes of the same sequence.
    row['speak_sequences'] = [s for i, s in enumerate(sequences)
        if i+1 == len(sequences) or sequences[i+1]['first_at'] != s['first_at']]
    row.update(control_p95_ms=percentile([e['control_ms'] for e in actions]),
        aggregation_p95_ms=percentile([e['aggregation_wait_ms'] for e in windows]),
        complete_windows=len(windows), observed_cycles=len(actions),
        merged_windows=ends[0]['merged_windows'], online_steps=ends[0]['steps'],
        eof_drain_events=ends[0]['eof_drain_events'],
        partial_windows=sum(e['kind'] == 'eof_partial_window' for e in events),
        state_transitions=sum(e['visible']['state'] != e['state_after'] for e in actions))
    return row


def interval_evidence(case, events):
    start = next((e['send_started_at'] for e in events if e['kind'] == 'input_timing' and
                  'send_started_at' in e), None)
    results = [e for e in events if e['kind'] == 'control_result']
    rows = []
    for index, interval in enumerate(case.get('annotations', {}).get('pause.json', [])):
        lo, hi = interval['timestamp']
        covered = [e for e in results if lo*1000 <= e['window']['nominal_end_ms'] <= hi*1000]
        rows.append({'case_id': case['case_id'], 'pause_index': index, 'start_seconds': lo,
            'end_seconds': hi, 'duration_seconds': hi-lo, 'observed_cycles': len(covered),
            'speak_cycles': sum(e.get('state_after') == 'Speak' for e in covered),
            'starts': sum(e.get('action') == 'start' for e in covered),
            'asr_prefixes': [e.get('visible', {}).get('user_text') for e in covered],
            'observations': [e.get('visible', {}).get('observation') for e in covered],
            'send_started_at': start, 'attribution': 'evidence_only_not_semantic_error_label'})
    return rows


def run(manifest_path, replay_root, output):
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('protocol', {}).get('controller_state_mode') != 'action_only':
        raise ValueError('Legacy simulated-response runs must not be scored as action-only monitoring')
    control_ms = manifest.get('protocol', {}).get('control_ms', 480)
    if not manifest['complete'] or len(manifest['records']) != 100:
        raise ValueError('Expected frozen 50+50 planned denominator')
    output.mkdir(parents=True, exist_ok=False)
    rows, intervals, all_control, all_aggregation = [], [], [], []
    for case in manifest['records']:
        path = replay_root / 'traces' / (case['case_id'] + '.jsonl')
        try:
            events = [json.loads(line) for line in path.read_text().splitlines()]
            row = score_case(case, events, control_ms)
            intervals.extend(interval_evidence(case, events))
            all_control.extend(e['control_ms'] for e in events if e['kind'] == 'control_result' and 'control_ms' in e)
            all_aggregation.extend(e['aggregation_wait_ms'] for e in events if e['kind'] == 'control_window')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row = score_case(case, [], control_ms)
            row['unknown_reason'] = 'unreadable_trace: ' + repr(exc)
        rows.append(row)
    smooth = [r for r in rows if r['subset'] == 'candor_turn_taking']
    pause = [r for r in rows if r['subset'] == 'candor_pause_handling']
    waits = [r['start_wait_beats'] for r in smooth if r['post_asr_start'] and r['start_wait_beats'] is not None]
    summary = {'schema_version': 1, 'planned': 100, 'control_ms': control_ms,
        'three_cycles_nominal_ms': 3 * control_ms, 'turn_taking': {
        'post_asr_speak': proportion([r['post_asr_speak'] for r in smooth]),
        'post_asr_start': proportion([r['post_asr_start'] for r in smooth]),
        'start_wait_beats_mean': statistics.mean(waits) if waits else None,
        'start_wait_ms_mean': statistics.mean(waits) * control_ms if waits else None,
        'start_wait_valid_samples': len(waits),
        'start_timing_unknown_samples': sum(r['start_timing_unknown'] for r in smooth)},
        'pause_handling': {'pre_asr_three_speak': proportion([r['pre_asr_three_speak'] for r in pause])},
        'control_p95_ms': percentile(all_control), 'aggregation_p95_ms': percentile(all_aggregation),
        'pause_intervals': len(intervals), 'controller_state_mode': 'action_only',
        'interpretation': 'controller actions and state only; not actual audio latency or official TOR'}
    for name, value in [('summary.json', summary), ('intervals.json', intervals)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    with (output / 'cases.csv').open('w', newline='') as stream:
        fields = sorted(set().union(*(r.keys() for r in rows)))
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})
    (output / 'README.md').write_text(f'# FDB {control_ms}ms周期联合结果\n\n'
        f'一拍为{control_ms}ms，连续3周期名义覆盖{3*control_ms}ms；跨周期对照须同时查看实际毫秒。\n\n'
        '本结果仅监控ASR更新边界附近的TextTurn动作与状态，不模拟回答、生成或播放；不代表真实扬声器开口或官方TOR。'
        '每臂计划分母固定50；未运行、失败和关键trace缺失保留未知。\n\n'
        '主比例、Wilson95%区间与等待拍数有效分母见summary.json；逐录音见cases.csv，'
        '停顿区间ASR前缀和覆盖证据见intervals.json。区间证据不自动构成语义错误判断。\n\n'
        '```json\n' + json.dumps(summary, ensure_ascii=False, indent=2) + '\n```\n')
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.manifest, args.replay, args.output)
