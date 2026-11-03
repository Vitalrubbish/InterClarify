"""Score fixed native frontend runs without replacing their failed denominators."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'remote'))
from nemotron_teacher_fdb import word_errors
from x2_streaming_probe import digest, distribution, write_json
from analyze_native_frontend import MANIFEST_SHA256, audit_condition, load_rows

COORDINATES = ('main', 'observed', 'available', 'published', 'read')
TASKS = ('smooth_turn_taking', 'pause_handling', 'user_interruption')


def score_times(sample, events, coordinate):
    selected = [(event, event['times'][coordinate]) for event in events if coordinate in event['times']]
    complete = [at for event, at in selected if event['accepted'] and event['token'] == '<|user_complete|>']
    result = {'complete_events': len(complete)}
    if sample['task'] == 'pause_handling':
        result['pause_intervals'] = [{'start': item['timestamp'][0], 'end': item['timestamp'][1],
            'complete_events': sum(item['timestamp'][0] <= at < item['timestamp'][1] for at in complete)}
            for item in sample['annotation']]
    else:
        left, right = sample['annotation'][0]['timestamp']
        boundary = left if sample['task'] == 'smooth_turn_taking' else right
        start = 0 if sample['task'] == 'smooth_turn_taking' else left
        relevant = [at for at in complete if at >= start]
        result.update(early_complete=sum(at < boundary for at in relevant),
                      over_160ms_early=sum(at < boundary - .16 for at in relevant),
                      after_boundary_complete=sum(at >= boundary for at in relevant))
        if sample['task'] == 'user_interruption':
            nonidle = [at for event, at in selected if event['accepted'] and event['token'] == '<|user_nonidle|>' and left <= at <= right]
            result.update(nonidle_detected=bool(nonidle), nonidle_delay_ms=(nonidle[0] - left) * 1000 if nonidle else None)
    return result


def score_case(sample, record, rows, dual):
    start = record.get('started_at')
    if start is None and rows:
        first = rows[0]
        start = first['released_at'] - first['controller_main_lag_ms'] / 1000 - first['receipts']['controller']['state']['state_processed_until'] / 16000
    events, completions, continuations, first_text = [], [], [], None
    previous_text = ''
    final_text = record.get('online_text', '') if dual else None
    for row in rows:
        control = row['receipts']['controller']
        state = control['state']
        times = {'main': state['state_processed_until'] / 16000,
                 'observed': state['state_observed_until'] / 16000,
                 'available': state['state_available_at'] - start,
                 'published': row.get('batch_published_at', row['released_at']) - start}
        if 'read_at' in row:
            times['read'] = row['read_at'] - start
        events.append({'step_id': row['step_id'], 'token': state['state_token'], 'raw_token': state['raw_token'],
                       'accepted': state['state_accepted'], 'rule_applied': state['rule_applied'], 'times': times})
        if dual:
            text = row['snapshot']['text']
            if text and first_text is None:
                first_text = {'step_id': row['step_id'], 'published_seconds': times['published'],
                              'read_seconds': times.get('read'), 'asr_observed_seconds': row['snapshot']['text_observed_until'] / 16000}
            for frame in row['receipts']['asr']['frames']:
                candidate = frame['text']
                delta = candidate[len(previous_text):] if candidate.startswith(previous_text) else ''
                if (frame['decision'] == 33 and previous_text and delta and previous_text[-1].isalnum() and delta[0].isalnum()):
                    continuations.append({'step_id': row['step_id'], 'frame_index': frame['frame_index'],
                                          'previous_suffix': previous_text[-64:], 'delta_prefix': delta[:64]})
                previous_text = candidate
            if state['state_accepted'] and state['state_token'] == '<|user_complete|>':
                prefix_ok = final_text.startswith(text)
                completions.append({'step_id': row['step_id'], 'times': times, 'text': text,
                    'later_closed_text': final_text[len(text):] if prefix_ok else None,
                    'prefix_preserved': prefix_ok, 'controller_completed_at': control['completed_at'],
                    'asr_completed_at': row['receipts']['asr']['completed_at']})
    coordinates = {name: score_times(sample, events, name) for name in COORDINATES if name != 'read' or dual}
    result = {'case_id': sample['case_id'], 'task': sample['task'], 'passed': record.get('passed', False),
        'frames': len(rows), 'coordinates': coordinates, 'raw_model_counts': dict(Counter(event['raw_token'] for event in events)),
        'native_state_counts': dict(Counter(event['token'] for event in events)),
        'rule_adjustments': sum(event['rule_applied'] for event in events), 'first_text': first_text,
        'completion_snapshots': completions, 'cross_group_continuation_candidates': continuations,
        'online_text': final_text, 'unprocessed_real_samples': record.get('diagnostics', {}).get('unprocessed_real_samples'),
        'asr_tail': record.get('diagnostics', {}).get('asr') if dual else None,
        'drain_performed': False, 'tail_status': 'unknown', 'events': events,
        'publication_kind': 'joint_context' if dual else 'native_service_return',
        'runtime_error': record.get('ingress_error') or record.get('error')}
    if dual and sample['reference'] is not None:
        result['word_errors'] = word_errors(sample['reference'], final_text)
    return result


def compare_inputs(single, dual):
    def key(row):
        receipt = row['receipts']['controller']
        return (receipt['state']['state_processed_until'], receipt['state']['state_observed_until'],
                *(receipt['windows'][name]['sha256'] for name in ('main', 'lookback', 'lookahead')))

    def values(row):
        receipt = row['receipts']['controller']
        audio = next((event.get('audio_token_ids') for event in receipt['events']
                      if event['kind'] == 'stage' and event['name'] == '_audio_to_tokens'), None)
        state = receipt['state']
        return {'audio_token_ids': audio, 'control_text': state['control_text'], 'control_delta': state['control_delta'],
                'raw_token': state['raw_token'], 'native_state': state['state_token'], 'rule_applied': state['rule_applied']}
    left, right = {key(row): row for row in single}, {key(row): row for row in dual}
    common = left.keys() & right.keys()
    differences = []
    for item in sorted(common):
        a, b = values(left[item]), values(right[item])
        changed = [name for name in a if a[name] != b[name]]
        if changed:
            differences.append({'processed_until': item[0], 'observed_until': item[1], 'changed': changed,
                                'single_step': left[item]['step_id'], 'dual_step': right[item]['step_id']})
    return {'matched_windows': len(common), 'unmatched_single': len(left) - len(common),
            'unmatched_dual': len(right) - len(common), 'differences': differences}


def task_summary(cases):
    result = {}
    for task in TASKS:
        selected = [case for case in cases if case['task'] == task]
        summary = {'fixed_cases': len(selected), 'completed_cases': sum(case['passed'] for case in selected), 'coordinates': {}}
        for coordinate in COORDINATES:
            values = [case['coordinates'][coordinate] for case in selected if coordinate in case['coordinates']]
            if not values:
                continue
            group = {'scored_cases': len(values), 'complete_events': sum(value['complete_events'] for value in values)}
            for field in ('early_complete', 'over_160ms_early', 'after_boundary_complete', 'nonidle_detected'):
                if any(field in value for value in values):
                    group['cases_with_' + field] = sum(bool(value.get(field)) for value in values)
            if task == 'pause_handling':
                intervals = [interval for value in values for interval in value['pause_intervals']]
                group.update(pause_intervals=len(intervals), intervals_with_complete=sum(v['complete_events'] > 0 for v in intervals))
            if task == 'user_interruption':
                group['nonidle_delay_ms'] = distribution([v['nonidle_delay_ms'] for v in values if v['nonidle_delay_ms'] is not None])
            summary['coordinates'][coordinate] = group
        scores = [case['word_errors'] for case in selected if 'word_errors' in case]
        words = sum(score['reference_words'] for score in scores)
        errors = sum(score['errors'] for score in scores)
        summary['online_word_errors'] = {'scored_cases': len(scores), 'reference_words': words, 'errors': errors,
                                         'wer': errors / words if words else None}
        result[task] = summary
    return result


def summarize_arm(run, condition, output):
    manifest = json.loads((run / 'frozen_manifest.json').read_text())
    if digest(run / 'frozen_manifest.json') != MANIFEST_SHA256 or len(manifest['samples']) != 30:
        raise ValueError('Formal analysis requires the original fixed FDB30 manifest')
    root = run / condition
    result = json.loads((root / 'result.json').read_text())
    if result.get('suite') != 'fdb30':
        raise ValueError('Preflight evidence cannot be reported as formal FDB30')
    if digest(run / 'ntf018_acceptance.json') != result['acceptance_gate_sha256']:
        raise ValueError('Accepted NTF-018 evidence differs from the formal run')
    expected = [sample['case_id'] for sample in manifest['samples']]
    audit = audit_condition(run, condition, expected)
    records = {case['case_id']: case for case in result['cases']}
    cases, rows_by_case, all_rows = [], {}, []
    for sample in manifest['samples']:
        rows = load_rows(root, sample['case_id'])
        rows_by_case[sample['case_id']] = rows
        record = records.get(sample['case_id'], {'passed': False})
        cases.append(score_case(sample, record, rows, condition == 'dual-full'))
        all_rows.extend(rows)
    resource_rows = [line.split() for line in (run / 'resources.txt').read_text().splitlines()]
    peaks = {name: max((int(row[index]) for row in resource_rows), default=None)
             for name, index in [('gpu_mib', 2), ('rss_kib', 3), ('output_kib', 4)]}
    resource_ok = bool(resource_rows) and not (run / 'resource_stop.txt').exists() and all(
        peaks[name] <= limit for name, limit in [('gpu_mib', 22528), ('rss_kib', 33554432), ('output_kib', 131072)])
    controls = [row['receipts']['controller'] for row in all_rows]
    frames = [frame for row in all_rows for frame in row['receipts'].get('asr', {}).get('frames', [])]
    summary = {'condition': condition, 'passed': audit['passed'] and resource_ok,
        'fixed_cases': 30, 'completed_cases': sum(case['passed'] for case in cases), 'audit': audit,
        'resource_checks_passed': resource_ok, 'resource_peaks': peaks,
        'tasks': task_summary(cases), 'cases': cases,
        'acceptance_gate_sha256': result['acceptance_gate_sha256'],
        'controller_main_ms': distribution([row['controller_main_lag_ms'] for row in all_rows]),
        'first_frame_main_ms': distribution([rows[0]['controller_main_lag_ms'] for rows in rows_by_case.values() if rows]),
        'stable_main_ms': distribution([row['controller_main_lag_ms'] for rows in rows_by_case.values() for row in rows[1:]]),
        'controller_observed_ms': distribution([row['controller_observed_lag_ms'] for row in all_rows]),
        'controller_compute_ms': distribution([(row['completed_at'] - row['started_at']) * 1000 for row in controls]),
        'asr_main_ms': distribution([row['asr_main_lag_ms'] for row in all_rows if 'asr_main_lag_ms' in row]),
        'asr_compute_ms': distribution([(frame['completed_at'] - frame['started_at']) * 1000 for frame in frames]),
        'group_close_delay_ms': distribution([frame['decode']['group_close_delay_ms'] for frame in frames
                                            if frame.get('decode', {}).get('group_close_delay_ms') is not None]),
        'closed_progress_to_publication_ms': distribution([(row['batch_published_at'] - frame['asr_progress_available_at']) * 1000
            for row in all_rows for frame in row['receipts'].get('asr', {}).get('frames', []) if frame['decision'] == 33]),
        'first_text_visible_seconds': distribution([case['first_text']['published_seconds'] for case in cases if case['first_text']]),
        'state_available_to_publication_ms': distribution([(row.get('batch_published_at', row['released_at']) -
            row['receipts']['controller']['state']['state_available_at']) * 1000 for row in all_rows]),
        'max_unread_samples': max((max(row['unread_samples'].values()) for row in all_rows), default=0),
        'max_pcm_bytes': max((row['pcm_bytes'] for row in all_rows), default=0)}
    with (output / f'{condition}.backlog.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(['case_id', 'step_id', 'controller_main_ms', 'controller_observed_ms', 'asr_main_ms', 'unread_controller', 'unread_asr'])
        for name, rows in rows_by_case.items():
            for row in rows:
                writer.writerow([name, row['step_id'], row['controller_main_lag_ms'], row['controller_observed_lag_ms'],
                                 row.get('asr_main_lag_ms'), row['unread_samples']['controller'], row['unread_samples'].get('asr')])
    return summary, rows_by_case, manifest


def analyze(dual_run, single_run, output):
    output.mkdir(parents=True, exist_ok=True)
    dual, dual_rows, manifest = summarize_arm(dual_run, 'dual-full', output)
    single, single_rows, other = summarize_arm(single_run, 'single-full', output)
    if manifest != other or dual['acceptance_gate_sha256'] != single['acceptance_gate_sha256']:
        raise ValueError('The two arms do not share the same frozen input and gate')
    pairs = {sample['case_id']: compare_inputs(single_rows[sample['case_id']], dual_rows[sample['case_id']]) for sample in manifest['samples']}
    result = {'engineering_passed': dual['passed'], 'single_reference_passed': single['passed'],
              'manifest_sha256': MANIFEST_SHA256, 'dual': dual, 'single': single, 'input_comparison': pairs}
    write_json(output / 'comparison.json', result)
    return result


def write_plot(dual_run, single_run, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    manifest = json.loads((dual_run / 'frozen_manifest.json').read_text())
    figure, axes = plt.subplots(3, 2, figsize=(13, 9), sharey=True)
    for column, (run, condition, title) in enumerate(((single_run, 'single-full', 'Native single lane'),
                                                    (dual_run, 'dual-full', 'Native control + independent X2'))):
        for index, task in enumerate(TASKS):
            axis = axes[index, column]
            for sample in manifest['samples']:
                if sample['task'] != task:
                    continue
                rows = load_rows(run / condition, sample['case_id'])
                axis.plot([row['receipts']['controller']['state']['state_processed_until'] / 16000 for row in rows],
                          [row['controller_main_lag_ms'] for row in rows], linewidth=.8, alpha=.65)
            axis.axhline(800, color='red', linestyle='--', linewidth=1)
            axis.set(title=title + '\n' + task, xlabel='Actual controller main end (seconds)', ylabel='Main latency (ms)')
            axis.grid(alpha=.2)
    figure.suptitle('NTF-019 fixed FDB30: published native-control latency; each line is one case')
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dual', type=Path, required=True)
    parser.add_argument('--single', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plot', type=Path)
    args = parser.parse_args()
    result = analyze(args.dual, args.single, args.output)
    if args.plot:
        write_plot(args.dual, args.single, args.plot)
    print(json.dumps({'engineering_passed': result['engineering_passed'],
                      'dual_completed': result['dual']['completed_cases'], 'single_completed': result['single']['completed_cases']}))
