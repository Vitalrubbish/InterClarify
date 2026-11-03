"""Audit fixed native frontend evidence without loading models or rewriting runs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import gzip
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'remote'))
from x2_streaming_probe import distribution, write_json

CASES = ['candor_turn_taking-102', 'candor_pause_handling-127', 'synthetic_user_interruption-104']
CONDITIONS = ['dual-limited', 'dual-full', 'single-full']
MANIFEST_SHA256 = '403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07'


def load_rows(root, case_id):
    path = root / f'{case_id}.frames.jsonl'
    if path.exists():
        stream = path.open()
    elif Path(str(path) + '.gz').exists():
        stream = gzip.open(str(path) + '.gz', 'rt', encoding='utf-8')
    else:
        return []
    with stream:
        return [json.loads(line) for line in stream if line.strip()]


def audit_case(rows, result, dual):
    failures, previous_release, text, groups = [], 0., '', 0
    expected = (result['real_samples'] + 2559) // 2560
    count_valid = len(rows) == expected if dual else len(rows) >= expected
    if not result.get('passed') or not count_valid or result.get('frames') != len(rows):
        failures.append('fixed_case_incomplete')
    for index, row in enumerate(rows):
        control = row['receipts']['controller']
        if row['step_id'] != index or control['started_at'] < previous_release:
            failures.append(f'{index}:controller_sequence')
        if control['completed_at'] > row['released_at']:
            failures.append(f'{index}:release_before_controller')
        if row.get('pcm_bytes', 0) > 4 * 2**20:
            failures.append(f'{index}:pcm_overload')
        if dual:
            snapshot, receipt = row['snapshot'], row['receipts']['asr']
            frames = receipt['frames']
            if not frames or any(frame['started_at'] < previous_release for frame in frames):
                failures.append(f'{index}:asr_sequence')
            for offset, frame in enumerate(frames):
                tokens = frame.get('decode', {}).get('token_ids', [])
                if frame['frame_index'] != index * 2 + offset:
                    failures.append(f'{index}:asr_frame_index')
                if frame['decision'] == 33:
                    groups += 1
                    if len(tokens) < 2 or tokens[0] != 33 or tokens[-1] != 2 or any(v in (1, 2, 32, 33) for v in tokens[1:-1]):
                        failures.append(f'{index}:invalid_eos')
                elif frame['decision'] != 32 or tokens != [32]:
                    failures.append(f'{index}:invalid_wait')
                if frame['committed_groups'] != groups or not frame['text'].startswith(text):
                    failures.append(f'{index}:text_or_group_integrity')
                if frame['decision'] == 32 and frame['text'] != text:
                    failures.append(f'{index}:wait_changed_text')
                text = frame['text']
            completed = max(control['completed_at'], receipt['completed_at'])
            published = snapshot['batch_published_at']
            if not completed <= published <= row['released_at'] <= row['read_at']:
                failures.append(f'{index}:publication_order')
            if (snapshot['step_id'] != index or snapshot['text'] != text or snapshot['committed_groups'] != groups
                    or snapshot['state_token'] != control['state']['state_token']
                    or snapshot['state_available_at'] != control['state']['state_available_at']
                    or snapshot['source'] != 'x2_streaming_asr'
                    or snapshot['state_published_at'] != published
                    or snapshot['asr_processed_until'] < snapshot['state_observed_until']
                    or snapshot['open_group_tokens'] or snapshot['decoding']):
                failures.append(f'{index}:invalid_joint_snapshot')
        previous_release = row['released_at']
    return {'passed': not failures, 'failures': failures, 'frames': len(rows), 'expected_frames': expected,
            'closed_groups': groups if dual else None, 'online_text': text if dual else None,
            'controller_main_ms': distribution([row['controller_main_lag_ms'] for row in rows]),
            'controller_observed_ms': distribution([row['controller_observed_lag_ms'] for row in rows]),
            'asr_main_ms': distribution([row['asr_main_lag_ms'] for row in rows if dual]),
            'first_frame_main_ms': rows[0]['controller_main_lag_ms'] if rows else None,
            'stable_main_ms': distribution([row['controller_main_lag_ms'] for row in rows[1:]]),
            'failed_step_sensevoice': [{'samples': sum(span['samples'] for span in event['spans']),
                'dtype': event['dtype'], 'milliseconds': (event['completed_at'] - event['started_at']) * 1000}
                for event in result.get('diagnostics', {}).get('controller_events', [])
                if not result.get('passed') and event['kind'] == 'sensevoice']}


def warmup_details(root, warmup):
    details = []
    for index, record in enumerate(warmup.get('rounds', [])):
        rows = [json.loads(line) for line in (root / f'warmup_{index}.frames.jsonl').read_text().splitlines()]
        controls = [row['receipts']['controller'] for row in rows]
        events = [event for row in controls for event in row['events']]
        senses = [event for event in events if event['kind'] == 'sensevoice']
        details.append({'frames': record['frames'], 'passed': record['passed'], 'coverage': record['coverage'],
            'raw_states': dict(Counter(row['state']['raw_token'] for row in controls)),
            'effective_states': dict(Counter(row['state']['state_token'] for row in controls)),
            'rejections': dict(Counter(row['state']['rejection_reason'] or 'accepted' for row in controls)),
            'controller_compute_ms': record['timing']['controller_compute_ms'],
            'x2_compute_ms': record['timing']['asr_compute_ms'],
            'sensevoice_ms': distribution([(event['completed_at'] - event['started_at']) * 1000 for event in senses]),
            'sensevoice_dtypes': sorted({event['dtype'] for event in senses}),
            'sensevoice_samples': sorted({sum(span['samples'] for span in event['spans']) for event in senses}),
            'sensevoice_calls': len(senses), 'direct_sensevoice': record['direct_sensevoice'],
            'cleanup': record['cleanup'],
            'unprocessed_real_samples': record['diagnostics']['unprocessed_real_samples']})
    return details


def audit_condition(run, condition, expected_cases=None):
    root, failures, cases = run / condition, [], []
    try:
        result = json.loads((root / 'result.json').read_text())
        if result.get('manifest_sha256') != MANIFEST_SHA256 or result.get('condition') != condition:
            failures.append('frozen_condition_or_manifest_changed')
        exit_code = int((run / f'{condition}.exit_code.txt').read_text())
        if exit_code or not result.get('passed'):
            failures.append('condition_failed')
        if [case['case_id'] for case in result['cases']] != (CASES if expected_cases is None else expected_cases):
            failures.append('fixed_cases_missing_or_changed')
        warmup = result.get('warmup', {})
        if not warmup.get('passed'):
            failures.append('warmup_failed')
        if condition != 'dual-limited':
            if (len(warmup.get('rounds', [])) != 2 or any(warmup.get('missing_by_round', [True]))
                    or not warmup.get('reset_rng_equal') or not warmup.get('equivalence', {}).get('passed')):
                failures.append('full_warmup_or_equivalence_missing')
        for case in result['cases']:
            rows = load_rows(root, case['case_id'])
            audited = audit_case(rows, case, condition != 'single-full')
            cases.append(dict(case_id=case['case_id'], **audited))
            if not audited['passed']:
                failures.append(case['case_id'] + ':audit_failed')
        return {'passed': not failures, 'failures': failures, 'exit_code': exit_code,
                'cases': cases, 'load_seconds': result.get('load_seconds'),
                'warmup_seconds': result.get('warmup_seconds'), 'warmup_passed': warmup.get('passed', False),
                'missing_paths': warmup.get('missing_by_round'), 'run_error': result.get('error'),
                'native_equivalence_passed': warmup.get('equivalence', {}).get('passed'),
                'warmup_details': warmup_details(root, warmup)}
    except Exception as exc:
        return {'passed': False, 'failures': failures + ['missing_or_invalid_evidence'],
                'error': str(exc), 'cases': cases}


def analyze(run):
    conditions = {condition: audit_condition(run, condition) for condition in CONDITIONS}
    resource_stop = (run / 'resource_stop.txt').exists()
    resource_rows = [line.split() for line in (run / 'resources.txt').read_text().splitlines()] if (run / 'resources.txt').exists() else []
    peaks = {name: max((int(row[column]) for row in resource_rows), default=None)
             for name, column in [('gpu_mib', 2), ('rss_kib', 3), ('output_kib', 4)]}
    resource_ok = bool(resource_rows) and not resource_stop and all(
        peaks[name] <= limit for name, limit in [('gpu_mib', 22528), ('rss_kib', 33554432), ('output_kib', 131072)])
    return {'conditions': conditions, 'resource_stop': resource_stop, 'resource_peaks': peaks,
            'resource_checks_passed': resource_ok,
            'ntf019_candidate_gate': conditions['dual-full']['passed'] and resource_ok,
            'matrix_all_passed': all(value['passed'] for value in conditions.values()) and resource_ok}


def write_backlog_plot(run, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(3, 1, figsize=(8, 7), sharey=True)
    for axis, case in zip(axes, CASES):
        path = run / 'dual-limited' / f'{case}.frames.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        steps = [row['step_id'] for row in rows]
        axis.plot(steps, [row['controller_main_lag_ms'] for row in rows], 'o-', label='Controller main to joint release')
        axis.plot(steps, [row['asr_main_lag_ms'] for row in rows], 's-', label='X2 main to joint publication')
        axis.set(title=case + ' (incomplete)', ylabel='Latency (ms)', xticks=steps)
        axis.grid(alpha=.2)
    axes[0].legend(fontsize=8, loc='lower right')
    axes[-1].set_xlabel('Published 160 ms batch index; failed/unpublished batches are omitted')
    figure.suptitle('NTF-018 limited warmup: fixed three-axis partial traces')
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plot', type=Path)
    args = parser.parse_args()
    write_json(args.output, analyze(args.run))
    if args.plot:
        write_backlog_plot(args.run, args.plot)
