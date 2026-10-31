"""Audit independent ASR pairing and compare fixed, common complete coverage."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from compare_nemotron_teacher import distribution, metrics, read_frames, word_errors


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def audit_case(frames, source, native):
    produced = {v['processed_until']: v for v in source if v['audit_kind'] == 'frame_source'}
    previous = 0
    for frame in frames:
        end = frame['processed_until']
        assert (0 < end <= 2560 if previous == 0 else end == previous + 2560), 'Missing, duplicate or reordered published state'
        original = produced[end]
        required = max(end, original['audio_observed_until'])
        first = next(v for v in native if v['feature_end_sample'] >= required)
        assert frame['native_step'] == first, 'Not the first sufficient completed native snapshot'
        assert frame['text'] == first['text'], 'Published text differs from its frozen native step'
        for key in ('state_token', 'state_token_id', 'raw_token', 'state_accepted',
                    'controller_generation', 'state_resolved_at', 'controller_completed_at',
                    'control_text', 'delta_text'):
            assert frame[key] == original[key], f'Cached state changed: {key}'
        assert first['consumed_samples'] == first['feature_end_sample'] <= first['received_samples']
        assert frame['audio_observed_until'] == max(required, first['feature_end_sample'])
        assert frame['state_resolved_at'] <= frame['controller_completed_at'] <= frame['published_at']
        assert first['decode_completed_at'] <= frame['published_at']
        previous = end
    return {'audited_frames': len(frames), 'produced_states': len(produced)}


def summarize(root):
    manifest = json.loads((root / 'probe/input_manifest.json').read_text())
    result = json.loads((root / 'probe/result.json').read_text())
    records = {r['case_id']: r for r in result['cases']}
    rows = []
    for sample in manifest['samples']:
        case = sample['case_id']
        record = records.get(case, {'passed': False, 'error': 'not_run'})
        frames = read_frames(root, case)
        source = read_lines(root / 'probe' / (case + '.source.jsonl'))
        native = read_lines(root / 'probe' / (case + '.native.jsonl'))
        audit = audit_case(frames, source, native)
        produced = [dict(v, backlog_ms=(v['state_resolved_at'] - record['playback_started_at']
                          - v['processed_until'] / 16000) * 1000)
                    for v in source if v['audit_kind'] == 'frame_source']
        row = {'case_id': case, 'task': sample['task'], 'passed': record['passed'],
               'error': record.get('error'), 'audit': audit, 'published': metrics(sample, frames),
               'produced': metrics(sample, produced), 'unpublished_states': record.get('unpublished_states'),
               'queue_peaks': record.get('queue_peaks'), 'ingress': record.get('ingress'),
               'native_pcm': record.get('native_pcm'),
               'direct_stop': [v for v in source if v['audit_kind'] == 'direct_stop'],
               'publication_main_ms': distribution([v['backlog_ms'] for v in frames]),
               'publication_observed_ms': distribution([v['observed_backlog_ms'] for v in frames]),
               'state_to_publication_ms': distribution([v['publication_wait_ms'] for v in frames]),
               'controller_to_publication_ms': distribution([v['pair_wait_after_controller_ms'] for v in frames]),
               'controller_compute_ms': distribution([(v['controller_completed_at'] - v['controller_started_at']) * 1000 for v in produced]),
               'native_compute_ms': distribution([(v['decode_completed_at'] - v['decode_started_at']) * 1000 for v in native]),
               'native_input_wait_ms': distribution([(v['pcm']['read_ready_at'] - v['pcm']['read_started_at']) * 1000
                                                     for v in native if v.get('pcm', {}).get('read_ready_at')]),
               'controller_ready_queue_ms': distribution([(v['controller_started_at'] - record['playback_started_at']
                   - v['audio_observed_until'] / 16000) * 1000 for v in produced]),
               'state_counts': dict(Counter(v['state_token'] for v in produced))}
        rows.append(row)
    return {'manifest_sha256': result['manifest_sha256'], 'source_commit': result['source_commit'],
            'fixed_count': len(manifest['samples']), 'complete': sum(r['passed'] for r in rows),
            'failed': [r['case_id'] for r in rows if not r['passed']], 'samples': rows}


def compare(root, baseline):
    current_result = json.loads((root / 'probe/result.json').read_text())
    old_result = json.loads((baseline / 'probe/result.json').read_text())
    if current_result['manifest_sha256'] != old_result['manifest_sha256']:
        raise ValueError('Comparison input manifest digests differ')
    manifest = json.loads((root / 'probe/input_manifest.json').read_text())
    current = {r['case_id']: r for r in current_result['cases']}
    old = {r['case_id']: r for r in old_result['cases']}
    rows = []
    for sample in manifest['samples']:
        case = sample['case_id']
        if not current.get(case, {}).get('passed') or not old.get(case, {}).get('passed'):
            continue
        new_frames, old_frames = read_frames(root, case), read_frames(baseline, case)
        end = min(new_frames[-1]['processed_until'] if new_frames else 0,
                  old_frames[-1]['processed_until'] if old_frames else 0)
        row = {'case_id': case, 'task': sample['task'], 'common_audio_end_sample': end}
        for label, frames in (('baseline', old_frames), ('dual', new_frames)):
            common = [v for v in frames if v['processed_until'] <= end]
            row[label] = {'full': metrics(sample, frames), 'common_audio': metrics(sample, common),
                          'publication_main_ms': distribution([v['backlog_ms'] for v in common]),
                          'publication_observed_ms': distribution([v['observed_backlog_ms'] for v in common])}
            if sample['reference'] is not None:
                row[label]['online_word_errors'] = word_errors(sample['reference'], (old if label == 'baseline' else current)[case]['online_text'])
                row[label]['common_audio_word_errors'] = word_errors(sample['reference'], common[-1]['text'] if common else '')
        rows.append(row)
    return {'baseline_complete': sum(r['passed'] for r in old.values()),
            'dual_complete': sum(r['passed'] for r in current.values()),
            'common_complete': len(rows), 'samples': rows,
            'eof_note': 'baseline synthetic drain and dual real complete windows have different coverage'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run)
    if args.baseline:
        result['comparison'] = compare(args.run, args.baseline)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('samples', 'comparison')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
