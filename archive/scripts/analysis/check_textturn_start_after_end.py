"""Count start occurrences after actual delivery of each original audio recording."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re


def file_hash(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def normalized(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def collect_case(case, path):
    row = {'case_id': case['case_id'], 'category': case['category'], 'source_id': case['source_id'],
           'audio_seconds': case['audio_seconds'], 'generation': None,
           'starts': [], 'reference_visible_at': None, 'lifecycle': [], 'control_errors': 0,
           'controls': [], 'reference_normalized': normalized(case['reference_text'])}
    if not path.exists():
        return row
    reference = normalized(case['reference_text'])
    generations = set()
    with path.open() as stream:
        for line in stream:
            event = json.loads(line)
            kind = event['kind']
            generation = event.get('generation') or event.get('asr_generation')
            if generation:
                generations.add(generation)
            if kind == 'context_publish' and reference and normalized(event['text']).startswith(reference):
                stamp = event['published_at']
                if row['reference_visible_at'] is None or stamp < row['reference_visible_at']:
                    row['reference_visible_at'] = stamp
            if kind == 'control_result':
                row['control_errors'] += bool(event.get('error'))
                visible = event.get('visible', {})
                row['controls'].append({'action': event.get('action'), 'error': event.get('error'),
                                        'state': visible.get('state'), 'observation': visible.get('observation'),
                                        'user_text': visible.get('user_text', ''),
                                        'empty_streak': visible.get('consecutive_no_voice_windows'),
                                        'ready_at': event.get('window', {}).get('input_ready_at'),
                                        'returned_at': event.get('returned_at')})
                if (event.get('action') == 'start' and not event.get('error')
                        and event.get('visible', {}).get('state') == 'Listen'):
                    row['starts'].append(event['returned_at'])
            if kind == 'simulated_lifecycle':
                row['lifecycle'].append(event)
    if len(generations) > 1:
        raise ValueError('Multiple ASR generations in a single case')
    row['generation'] = next(iter(generations), None)
    row['starts'].sort()
    return row


def end_diagnostics(case, audio_at):
    """Describe available end inputs without inventing a counterfactual Listen decision."""
    controls = case['controls']
    after = [c for c in controls if audio_at is not None and c['ready_at'] is not None
             and c['ready_at'] >= audio_at and not c['error'] and c['state'] == 'Listen']
    empty = [c for c in after if c['observation'] == '<|no-voice|>' and c['user_text'].strip()]
    full = [c for c in empty if normalized(c['user_text']).startswith(case['reference_normalized'])]
    first_start = next((c for c in controls if c['action'] == 'start' and not c['error']), None)
    if case['starts']:
        reason = 'start_observed'
    elif not after:
        reason = 'no_post_end_listen_control'
    elif not empty:
        reason = 'no_nonempty_user_silent_window'
    elif full:
        reason = 'full_reference_silent_keep'
    else:
        reason = 'different_or_partial_transcript_silent_keep'
    return {'post_end_listen_controls': len(after), 'post_end_nonempty_silent_controls': len(empty),
            'post_end_full_reference_silent_controls': len(full), 'no_start_reason': reason,
            'first_start_on_no_voice': first_start['observation'] == '<|no-voice|>' if first_start else None,
            'last_post_end_user_text': after[-1]['user_text'] if after else None,
            'max_post_end_empty_streak': max((c['empty_streak'] or 0 for c in after), default=0)}


def locate_audio_ends(rows, log_lines):
    wanted = {r['generation']: round(r['audio_seconds'] * 16000) * 2 for r in rows if r['generation']}
    if any(size <= 0 for size in wanted.values()):
        raise ValueError('Expected positive original audio duration')
    delivered, ends = Counter(), {}
    for line in log_lines:
        begin = line.find('{')
        if begin < 0 or '"asr_input"' not in line:
            continue
        event = json.loads(line[begin:])
        generation = event['session_id']
        if generation not in wanted or generation in ends or not event['bytes']:
            continue
        if event.get('eof') or event['bytes'] % 2:
            raise ValueError('Original audio boundary cannot be inferred from EOF or invalid PCM')
        delivered[generation] += event['bytes']
        if delivered[generation] >= wanted[generation]:
            ends[generation] = {'at': event['received_monotonic'],
                                'packet_ms': event['bytes'] / 32,
                                'delivered_bytes': delivered[generation], 'original_bytes': wanted[generation]}
    return ends


def classify(row, anchor):
    starts = row['starts']
    before = [t for t in starts if anchor is not None and t < anchor]
    after = [t for t in starts if anchor is not None and t >= anchor]
    return {'anchor_available': anchor is not None, 'any_start': bool(starts),
            'after_end_start': bool(after), 'after_end_within_1000ms': any(t - anchor <= 1 for t in after),
            'first_start_after_end': bool(starts) and anchor is not None and starts[0] >= anchor,
            'before_and_after': bool(before) and bool(after), 'before_only': bool(before) and not after,
            'never_start': not starts,
            'first_start_latency_ms': (starts[0] - anchor) * 1000 if starts and anchor is not None else None,
            'first_after_end_latency_ms': (after[0] - anchor) * 1000 if after else None}


def summarize(rows):
    result = {'planned': len(rows)}
    for prefix in ('audio', 'reference'):
        fields = ('anchor_available', 'any_start', 'after_end_start', 'after_end_within_1000ms',
                  'first_start_after_end', 'before_and_after', 'before_only', 'never_start')
        result[prefix] = {field: sum(bool(r[prefix + '_' + field]) for r in rows) for field in fields}
        known = result[prefix]['anchor_available']
        result[prefix].update(missing_anchor=len(rows) - known,
                             after_end_start_over_planned=result[prefix]['after_end_start'] / len(rows) if rows else None,
                             after_end_start_over_anchored=result[prefix]['after_end_start'] / known if known else None)
    return result


def run(args):
    if args.output.exists():
        raise ValueError('Use a fresh diagnostic directory')
    manifest = json.loads(args.manifest.read_text())
    cases = [c for c in manifest['records'] if c['category'] in ('smooth_question_pause', 'smooth_declarative')]
    if len({c['case_id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate case identity')
    compact = [collect_case(c, args.traces / (c['case_id'] + '.jsonl')) for c in cases]
    with args.asr_log.open() as stream:
        ends = locate_audio_ends(compact, stream)
    rows = []
    for case in compact:
        boundary = ends.get(case['generation'], {})
        audio_at = boundary.get('at')
        state = 'Listen'
        for event in sorted(case['lifecycle'], key=lambda e: e['at']):
            if audio_at is None or event['at'] > audio_at:
                continue
            if event.get('action') == 'start':
                state = 'Speak'
            elif event.get('action') == 'stop' or event.get('source_kind') == 'playback_complete':
                state = 'Listen'
        row = {k: case[k] for k in ('case_id', 'source_id', 'category', 'audio_seconds', 'generation', 'control_errors')}
        row.update(audio_end_packet_at=audio_at, audio_end_packet_ms=boundary.get('packet_ms'),
                   reference_visible_at=case['reference_visible_at'], start_count=len(case['starts']),
                   simulated_speaking_at_audio_end=state == 'Speak' if audio_at is not None else None)
        for prefix, anchor in [('audio', audio_at), ('reference', case['reference_visible_at'])]:
            row.update({prefix + '_' + key: value for key, value in classify(case, anchor).items()})
        row.update(end_diagnostics(case, audio_at))
        rows.append(row)
    idle = [r for r in rows if r['simulated_speaking_at_audio_end'] is False]
    absent = [r for r in rows if not r['audio_after_end_start']]
    late = [r for r in rows if r['audio_after_end_start'] and not r['audio_after_end_within_1000ms']]
    result = {'schema_version': 1, 'scope': 'saved_smooth_trace_occurrences_not_quality_scoring',
              'all': summarize(rows),
              'by_category': {category: summarize([r for r in rows if r['category'] == category])
                              for category in ('smooth_question_pause', 'smooth_declarative')},
              'speaking_at_audio_end': sum(r['simulated_speaking_at_audio_end'] is True for r in rows),
              'end_diagnostics': {
                  'idle_at_end': len(idle), 'idle_at_end_with_later_start': sum(r['audio_after_end_start'] for r in idle),
                  'no_later_start': len(absent),
                  'no_later_start_already_speaking': sum(r['simulated_speaking_at_audio_end'] is True for r in absent),
                  'later_start_over_1000ms': len(late),
                  'late_start_already_speaking': sum(r['simulated_speaking_at_audio_end'] is True for r in late),
                  'first_start_on_no_voice': sum(r['first_start_on_no_voice'] is True for r in rows),
                  'never_start_reasons': dict(Counter(r['no_start_reason'] for r in rows if r['audio_never_start']))},
              'identity': {'manifest_sha256': file_hash(args.manifest), 'asr_log_sha256': file_hash(args.asr_log),
                           'script_sha256': file_hash(__file__),
                           'trace_sha256': {c['case_id']: file_hash(args.traces / (c['case_id'] + '.jsonl'))
                                             for c in cases if (args.traces / (c['case_id'] + '.jsonl')).exists()}}}
    args.output.mkdir(parents=True)
    (args.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with (args.output / 'cases.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({k: v for k, v in result.items() if k != 'identity'}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--traces', type=Path, required=True)
    parser.add_argument('--asr-log', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
