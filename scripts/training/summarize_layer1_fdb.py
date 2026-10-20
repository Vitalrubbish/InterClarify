"""Collect final FDB evidence and compare response coverage with the frozen old T2."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from diagnose_layer1_fdb import aggregate, edit_counts, reference_text, words, TALKING
from layer1_model import sha256_file


def collect(run, condition, baseline):
    """Preserve failed samples and use the driver's response-specific playback anchors."""
    source = run / condition
    health = json.loads((source / 'model_health.json').read_text())
    if health['adaptation']['condition'] != condition:
        raise ValueError('Unexpected served candidate identity')
    previous = baseline['conditions']['T2']['rows']
    expected = {row['sample']: row for row in previous}
    rows = []
    for sample in sorted(expected):
        path = source / 'replay/fdb' / sample / 'a4_report.json'
        if not path.is_file():
            rows.append({'sample': sample, 'missing': True, 'status': 'MISSING',
                         'errors': ['Missing sample report']})
            continue
        record = json.loads(path.read_text())
        timeline_path = Path(record['timeline_path']) if record.get('timeline_path') else None
        events = ([json.loads(line) for line in timeline_path.read_text().splitlines()]
                  if timeline_path and timeline_path.is_file() else [])
        parsed = [r for r in events if r['event_type'] == 'duplex.protocol_parsed']
        ticks = [r for r in events if r['event_type'] == 'duplex.micro_turn_ready']
        final_asr = record.get('asr_final') or ''
        final_prefix = ticks[-1]['text'] if ticks else None
        stable = next((i for i in range(len(ticks)) if
                       all(t['text'] == final_prefix for t in ticks[i:])), None)
        threshold = ticks[stable]['monotonic_timestamp'] if stable is not None else float('inf')
        tail = [r for r in parsed if r['monotonic_timestamp'] >= threshold]
        controls = Counter(r['state_token'] for r in parsed if r.get('state_token'))
        tail_controls = Counter(r['state_token'] for r in tail if r.get('state_token'))
        reference, ref_source = reference_text(baseline['references'][sample])
        score = edit_counts(words(reference), words(final_asr)) if reference else None
        metrics = record.get('client_measurements', {})
        key = ('turn_taking' if sample.startswith('candor_turn_taking/') else
               'interruption_end' if sample.startswith('synthetic_user_interruption/') else None)
        latency = metrics.get('latencies', {}).get(key, {}) if key else {}
        delay = latency.get('to_playback_started_seconds')
        onset = latency.get('anchor_seconds', 0) + delay if delay is not None else None
        duration = record['input_audio_seconds']
        rows.append({'sample': sample, 'status': record['status'], 'errors': record.get('errors', []),
            'protocol_errors': record['timeline']['protocol_errors'], 'missing': False,
            'report_sha256': sha256_file(path),
            'timeline_sha256': sha256_file(timeline_path) if timeline_path and timeline_path.is_file() else None,
            'duration_seconds': duration, 'final_asr': final_asr, 'final_model_prefix': final_prefix,
            'final_prefix_matches_asr': final_asr == final_prefix, 'controls': dict(controls),
            'controls_after_final_asr': dict(tail_controls), 'micro_turns': len(ticks),
            'only_talking': bool(controls) and set(controls) == {TALKING},
            'only_talking_after_final_asr': bool(tail_controls) and set(tail_controls) == {TALKING},
            'has_voice': record['tts_audio_bytes'] > 0, 'tts_audio_bytes': record['tts_audio_bytes'],
            'new_response_playback_delay_seconds': delay,
            'new_response_playback_in_original_window': onset is not None and delay >= 0 and onset <= duration,
            'new_response_playback_in_diagnostic_tail': onset is not None and delay >= 0 and onset > duration,
            'finish_without_body': sum(r.get('state_token') == '<|user finish talking|>' and
                                       not r.get('text', '').strip() for r in parsed),
            'response_text': record.get('response', ''), 'client_measurements': metrics,
            'non_talking_events': [{k: r.get(k) for k in ('request_id', 'response_id', 'state_token', 'text', 'raw_output')}
                                   for r in parsed if r.get('state_token') != TALKING],
            'reference': reference, 'reference_source': ref_source, 'asr_score': score,
            'asr_equal_to_old_t2': final_asr == expected[sample]['final_asr'],
            'output_wav': record.get('output'), 'diagnostic_output_wav': record.get('diagnostic_output'),
            'sample_report': str(path)})
    present = [r for r in rows if not r['missing']]
    subsets = sorted({s.split('/')[0] for s in expected})
    summary = {'all': aggregate(present), 'subsets': {
        subset: aggregate([r for r in present if r['sample'].startswith(subset + '/')]) for subset in subsets}}
    failed = [r['sample'] for r in rows if r['status'] != 'PASS' or r.get('protocol_errors') or r['errors']]
    old = {}
    for row in previous:
        delay = row.get('client_measurements', {}).get('latencies', {})
        key = 'turn_taking' if row['sample'].startswith('candor_turn_taking/') else 'interruption_end'
        m = delay.get(key, {})
        seconds = m.get('to_playback_started_seconds')
        old[row['sample']] = seconds is not None and seconds >= 0 and m.get('anchor_seconds', 0) + seconds <= row['duration_seconds']
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'run': str(run), 'condition': condition,
        'exit_code': (run / 'exit_code.txt').read_text().strip() if (run / 'exit_code.txt').exists() else None,
        'condition_exit_code': (source / 'exit_code.txt').read_text().strip() if (source / 'exit_code.txt').exists() else None,
        'health': health, 'summary': summary, 'rows': rows, 'expected_samples': 25,
        'failed_or_missing_samples': failed, 'transport_passed': len(present) == 25 and not failed,
        'asr_equal_to_old_t2_samples': sum(r['asr_equal_to_old_t2'] for r in present),
        'coverage_changes': [{'sample': r['sample'], 'old': old[r['sample']],
            'new': r['new_response_playback_in_original_window']} for r in present
            if old[r['sample']] != r['new_response_playback_in_original_window']],
        'official_scoring': 'pending', 'manual_content_audio_review': 'pending',
        'physical_playback_measured': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('run', 'baseline', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--condition', default='T2_R2_paper_aligned')
    args = parser.parse_args()
    result = collect(args.run, args.condition, json.loads(args.baseline.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'health')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
