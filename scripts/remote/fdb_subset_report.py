"""Score frozen five-case FDB axes and summarize original-window diagnostics."""

import argparse
import json
from pathlib import Path

import full_fdb_two_axes as full


def score_subset(args):
    """Reuse the pinned official scorer with explicit subset coverage."""
    original_axes = full.AXES
    try:
        full.AXES = {name: (task, 5, annotation) for name, (task, _, annotation) in original_axes.items()}
        result = full.score(args)
    finally:
        full.AXES = original_axes
    path = args.output / 'summary.json'
    report = json.loads(path.read_text())
    report.update(corpus_scope='historical_frozen_subset', expected_sessions=10)
    full.write_json(path, report)
    return result


def summarize(root, output):
    """Separate transport, received playback, tail-only output and timing scores."""
    import soundfile as sf
    rows, groups = [], []
    subsets = ('candor_pause_handling', 'synthetic_pause_handling', 'candor_turn_taking',
               'synthetic_user_interruption', 'icc_backchannel')
    for subset in subsets:
        reports = sorted((root / 'fdb' / subset).glob('*/a4_report.json'))
        if len(reports) != 5:
            raise ValueError('Missing frozen subset reports: ' + subset)
        current = []
        for path in reports:
            lengths = []
            for name in ('input.wav', 'output.wav'):
                info = sf.info(str(path.parent / name))
                lengths.append(info.frames / info.samplerate)
            if abs(lengths[0] - lengths[1]) > 1 / 16000:
                raise ValueError('Official output includes a diagnostic tail: ' + str(path))
            report = json.loads(path.read_text())
            measurement = report['client_measurements']
            duration = report['input_audio_seconds']
            responses = measurement['responses']
            original = [r for r in responses if r.get('played_audio_bytes', 0) > 0
                        and r.get('playback_started_seconds', duration) < duration]
            tail = [r for r in responses if r.get('played_audio_bytes', 0) > 0 and r.get('playback_started_in_tail')]
            timeline = report['timeline']
            row = {'subset': subset, 'sample': path.parent.name, 'input_seconds': duration,
                   'transport_status': report['transport_status'],
                   'protocol_errors': timeline['protocol_errors'],
                   'played_in_original_window': bool(original), 'played_only_in_tail': bool(tail) and not original,
                   'no_played_audio_including_tail': measurement['no_played_audio'],
                   'responses': responses, 'latencies': measurement['latencies'],
                   'anchors': measurement['anchors']}
            rows.append(row)
            current.append(row)
        groups.append({'subset': subset, 'sessions': len(current),
                       'transport_passed': sum(r['transport_status'] == 'PASS' for r in current),
                       'played_in_original_window': sum(r['played_in_original_window'] for r in current),
                       'played_only_in_tail': sum(r['played_only_in_tail'] for r in current),
                       'silent_including_tail': sum(r['no_played_audio_including_tail'] for r in current)})
    result = {'sessions': len(rows), 'subsets': groups, 'samples': rows,
              'protocol_error_sessions': sum(bool(r['protocol_errors']) for r in rows),
              'official_wav_durations_verified': len(rows),
              'official_timing_separate': True, 'manual_content_review': 'pending',
              'note': 'Client playback onset is not aligned word onset; audio activity is not response correctness.'}
    full.write_json(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    scoring = sub.add_parser('score')
    for name in ('input', 'output', 'fdb-repo', 'scorer-python'):
        scoring.add_argument('--' + name, type=Path, required=True)
    scoring.set_defaults(defer_judge=True, judge_model='gpt-4-turbo', key_file=None,
                         base_url='https://api-2.xi-ai.cn/v1')
    summary = sub.add_parser('summarize')
    for name in ('root', 'output'):
        summary.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'score':
        raise SystemExit(score_subset(args))
    result = summarize(args.root, args.output)
    print(json.dumps({'sessions': result['sessions'], 'protocol_error_sessions': result['protocol_error_sessions']}))
