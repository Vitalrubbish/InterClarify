"""Compare frozen teacher runs on complete cases and common audio coverage."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'remote'))
from nemotron_teacher_fdb import word_errors


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    position = (len(values) - 1) * .95
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return {'count': len(values), 'p50': statistics.median(values),
            'p95': values[lower] + (values[upper] - values[lower]) * (position - lower), 'max': values[-1]}


def read_frames(root, case):
    path = root / 'probe' / (case + '.frames.jsonl')
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def metrics(sample, frames):
    accepted = [f for f in frames if f['state_accepted']]
    complete = [f for f in accepted if f['state_token'] == '<|user_complete|>']
    out = {'complete_events': len(complete)}
    task = sample['task']
    for axis, field in [('core', 'processed_until'), ('observed', 'audio_observed_until')]:
        if task == 'pause_handling':
            out[axis + '_pause_hits'] = [sum(a['timestamp'][0] <= f[field] / 16000 < a['timestamp'][1]
                                           for f in complete) for a in sample['annotation']]
        else:
            start = 0 if task == 'smooth_turn_taking' else sample['annotation'][0]['timestamp'][0]
            boundary = sample['annotation'][0]['timestamp'][0 if task == 'smooth_turn_taking' else 1]
            relevant = [f for f in complete if f['processed_until'] / 16000 >= start]
            early = [f for f in relevant if f[field] / 16000 < boundary]
            after = [f for f in relevant if f[field] / 16000 >= boundary]
            out[axis + '_early'] = len(early)
            out[axis + '_after'] = len(after)
            out[axis + '_strict'] = not early and bool(after)
            out[axis + '_after_ms'] = (after[0][field] / 16000 - boundary) * 1000 if after else None
            if axis == 'core':
                out['after_wall_ms'] = out['core_after_ms'] + after[0]['backlog_ms'] if after else None
    if task == 'user_interruption':
        start, boundary = sample['annotation'][0]['timestamp']
        nonidle = [f for f in accepted if f['state_token'] == '<|user_nonidle|>'
                   and start <= f['processed_until'] / 16000 <= boundary]
        out['nonidle'] = bool(nonidle)
        for axis, field in [('core', 'processed_until'), ('observed', 'audio_observed_until')]:
            out['nonidle_' + axis + '_ms'] = (nonidle[0][field] / 16000 - start) * 1000 if nonidle else None
        out['nonidle_wall_ms'] = out['nonidle_core_ms'] + nonidle[0]['backlog_ms'] if nonidle else None
    return out


def audit_teacher(frames):
    previous, last_release, feedback = '', None, None
    consumed, available, available_at, segments, lags = [], [], [], [], []
    pending_streak = maximum_streak = 0
    pending_ages, pending_age = [], 0
    for seq, f in enumerate(frames, 1):
        native = f['native_step']
        assert f['teacher_step_seq'] == seq and native['step_seq'] == seq + 1
        assert native['feature_end_sample'] == f['processed_until'] + 1584
        assert native['feature_end_sample'] <= native['received_samples']
        assert native['text'] == f['text'] == previous + f['raw_delta_text']
        assert native['decode_completed_at'] <= f['controller_started_at'] <= f['gate_resolved_at'] <= f['teacher_injected_at'] <= f['state_resolved_at'] <= f['published_at'] <= f['released_at']
        if last_release is not None:
            assert native['decode_started_at'] >= last_release
        assert f['feedback_state_id'] == feedback
        new = f['available_token_ids']
        common = 0
        for a, b in zip(available, new):
            if a != b:
                break
            common += 1
        available_at = available_at[:common] + [native['decode_completed_at']] * (len(new) - common)
        if f['gate_open']:
            assert f['gate_token_id'] != 151674
            shared = 0
            for a, b in zip(consumed, new):
                if a != b:
                    break
                shared += 1
            lags.extend((f['teacher_injected_at'] - value) * 1000 for value in available_at[shared:])
            assert f['consumed_token_ids'] == new
        else:
            assert f['gate_token_id'] == 151674
            assert f['consumed_token_ids'] == consumed and not f['teacher_token_ids']
            assert not f['cache_revision']
        for segment in f['cache_revision'].get('revised_segments', []):
            segments[segment['step'] - 1] = segment['ids']
        segments.append(f['teacher_token_ids'])
        assert [token for segment in segments for token in segment] == f['consumed_token_ids']
        pending = f['available_token_ids'] != f['consumed_token_ids']
        shared = 0
        for a, b in zip(f['consumed_token_ids'], new):
            if a != b:
                break
            shared += 1
        pending_age = (f['state_resolved_at'] - min(available_at[shared:], default=native['decode_completed_at'])) * 1000 if pending else 0
        if pending:
            pending_ages.append(pending_age)
        pending_streak = pending_streak + 1 if pending else 0
        maximum_streak = max(maximum_streak, pending_streak)
        previous, last_release = f['text'], f['released_at']
        feedback = f['state_token_id'] if f['state_accepted'] else None
        consumed, available = f['consumed_token_ids'], new
    return {'frames_checked': len(frames), 'token_available_to_input_ms': distribution(lags),
            'max_pending_streak_frames': maximum_streak,
            'pending_age_ms': distribution(pending_ages), 'eof_pending_age_ms': pending_age,
            'gate_open_frames': sum(f['gate_open'] for f in frames),
            'pending_frames': sum(f['available_token_ids'] != f['consumed_token_ids'] for f in frames),
            'eof_pending_range': frames[-1]['pending_token_range'] if frames else None,
            'cache_modes': dict(Counter(f['cache_revision'].get('replay_mode') for f in frames if f['cache_revision'])),
            'cache_replay_seconds': sum(f['cache_revision'].get('replay_seconds', 0) for f in frames)}


def group(rows, arm):
    output = {}
    for task in ('smooth_turn_taking', 'pause_handling', 'user_interruption'):
        selected = [r for r in rows if r['task'] == task]
        values = [r[arm] for r in selected]
        result = {'samples': len(values), 'complete_events': sum(v['complete_events'] for v in values)}
        if task == 'pause_handling':
            for axis in ('core', 'observed'):
                pauses = [n for v in values for n in v[axis + '_pause_hits']]
                result[axis + '_pause_intervals'] = len(pauses)
                result[axis + '_pause_hits'] = sum(n > 0 for n in pauses)
        else:
            for axis in ('core', 'observed'):
                for key in ('early', 'after', 'strict'):
                    result[axis + '_' + key + '_samples'] = sum(bool(v[axis + '_' + key]) for v in values)
            for key in ('after_wall_ms', 'core_after_ms', 'observed_after_ms'):
                result[key] = distribution([v[key] for v in values if v[key] is not None])
        if task == 'user_interruption':
            result['nonidle_samples'] = sum(v['nonidle'] for v in values)
            for key in ('nonidle_core_ms', 'nonidle_observed_ms', 'nonidle_wall_ms'):
                result[key] = distribution([v[key] for v in values if v[key] is not None])
        output[task] = result
    return output


def compare(baseline, candidate):
    manifest = json.loads((candidate / 'probe/input_manifest.json').read_text())
    manifests = json.loads((baseline / 'probe/input_manifest.json').read_text())
    assert manifest['samples'] == manifests['samples']
    results = {k: json.loads((v / 'probe/result.json').read_text()) for k, v in [('baseline', baseline), ('candidate', candidate)]}
    records = {k: {r['case_id']: r for r in result['cases']} for k, result in results.items()}
    rows, failures, audits = [], [], {}
    all_frames = {'baseline': [], 'candidate': []}
    for sample in manifest['samples']:
        name = sample['case_id']
        fs = {k: read_frames(root, name) for k, root in [('baseline', baseline), ('candidate', candidate)]}
        audits[name] = audit_teacher(fs['candidate'])
        if not all(records[k].get(name, {}).get('passed', False) for k in records):
            failures.append({'case_id': name, 'records': {k: records[k].get(name) for k in records},
                             'partial_frames': {k: len(v) for k, v in fs.items()}})
            continue
        cutoff = min(v[-1]['processed_until'] for v in fs.values())
        row = {'case_id': name, 'task': sample['task'], 'common_audio_end': cutoff}
        for k, frames in fs.items():
            row[k] = metrics(sample, frames)
            row[k + '_common'] = metrics(sample, [f for f in frames if f['processed_until'] <= cutoff])
            all_frames[k].extend(frames)
            if sample['reference'] is not None:
                row[k]['online_word_errors'] = word_errors(sample['reference'], records[k][name]['online_text'])
                row[k]['drained_word_errors'] = word_errors(sample['reference'], records[k][name]['drained_text'])
        rows.append(row)
    groups = {k: group(rows, k) for k in ('baseline', 'candidate', 'baseline_common', 'candidate_common')}
    for arm in ('baseline', 'candidate'):
        for task in ('pause_handling', 'user_interruption'):
            values = [r[arm] for r in rows if r['task'] == task]
            for mode in ('online', 'drained'):
                scores = [v[mode + '_word_errors'] for v in values]
                words = sum(v['reference_words'] for v in scores)
                errors = sum(v['errors'] for v in scores)
                groups[arm][task][mode + '_wer'] = {'words': words, 'errors': errors, 'wer': errors / words if words else None}
    paired = {}
    for task in ('smooth_turn_taking', 'user_interruption'):
        selected = [r for r in rows if r['task'] == task]
        for key in ('after_wall_ms', 'nonidle_wall_ms') if task == 'user_interruption' else ('after_wall_ms',):
            paired[task + '_' + key + '_candidate_minus_baseline'] = distribution([
                r['candidate'][key] - r['baseline'][key] for r in selected
                if r['candidate'][key] is not None and r['baseline'][key] is not None])
    return {'groups': groups, 'paired_wall_deltas_ms': paired, 'samples': rows, 'excluded': failures, 'teacher_audit': audits,
            'run_success': {k: {'passed': sum(r['passed'] for r in result['cases']), 'total': len(manifest['samples'])} for k, result in results.items()},
            'timing': {k: {'backlog_ms': distribution([f['backlog_ms'] for f in fs]),
                           'observed_backlog_ms': distribution([f['observed_backlog_ms'] for f in fs])} for k, fs in all_frames.items()},
            'states': {k: {'raw': dict(Counter(f['raw_token'] for f in fs)),
                           'effective': dict(Counter(f['state_token'] for f in fs)),
                           'adjustments': dict(Counter(str((f['adjustment'], f['state_token'])) for f in fs if f['adjustment'])),
                           'rejected': sum(not f['state_accepted'] for f in fs)} for k, fs in all_frames.items()}}


def main():
    parser = argparse.ArgumentParser()
    for name in ('baseline', 'candidate', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    value = compare(args.baseline, args.candidate)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in value.items() if k not in ('samples', 'teacher_audit', 'excluded')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
