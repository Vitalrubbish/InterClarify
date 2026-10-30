"""Freeze and inspect thirty real-time FDB replays with native ASR and SoulX."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import traceback

from nemotron_soulx_probe import run_case


SUBSETS = {
    'candor_turn_taking': ('smooth_turn_taking', 10, 'turn_taking.json'),
    'candor_pause_handling': ('pause_handling', 5, 'pause.json'),
    'synthetic_pause_handling': ('pause_handling', 5, 'pause.json'),
    'synthetic_user_interruption': ('user_interruption', 10, 'interrupt.json'),
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def freeze(args):
    import soundfile as sf
    if args.manifest.exists():
        raise FileExistsError(args.manifest)
    rng = random.Random(args.seed)
    samples = []
    for subset, (task, count, annotation) in SUBSETS.items():
        candidates = sorted((p for p in (args.input / subset).iterdir()
                             if p.is_dir() and (p / 'input.wav').is_file()), key=lambda p: p.name)
        for directory in sorted(rng.sample(candidates, count), key=lambda p: p.name):
            info = sf.info(str(directory / 'input.wav'))
            labels = json.loads((directory / annotation).read_text())
            if not labels or info.duration <= 0:
                raise ValueError(f'Missing labels or audio: {directory}')
            for label in labels:
                start, end = label['timestamp']
                if not 0 <= start <= end <= info.duration + .001:
                    raise ValueError(f'Invalid annotation: {directory}')
            names = ['input.wav', annotation]
            reference = None
            reference_end = None
            if (directory / 'transcription.json').is_file():
                names.append('transcription.json')
                transcription = json.loads((directory / 'transcription.json').read_text())
                reference = ' '.join(v['text'] for v in transcription)
                reference_end = max(v['timestamp'][1] for v in transcription)
            elif task == 'user_interruption':
                reference = labels[0]['context'] + ' ' + labels[0]['interrupt']
            samples.append({'case_id': subset + '-' + directory.name, 'subset': subset,
                            'task': task, 'id': directory.name, 'duration_seconds': info.duration,
                            'input': str((directory / 'input.wav').resolve()),
                            'files': {name: digest(directory / name) for name in names},
                            'annotation': labels, 'reference': reference,
                            'reference_end_seconds': reference_end})
    total = sum(s['duration_seconds'] for s in samples)
    if len(samples) != 30 or total > 1200:
        raise ValueError(f'Frozen sample budget exceeded: {len(samples)} clips, {total}s')
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.manifest, {'schema_version': 1, 'seed': args.seed,
                              'total_audio_seconds': total, 'samples': samples,
                              'tail_seconds_added': 0, 'selection': 'sorted IDs, seeded sampling without replacement'})
    print(json.dumps({'manifest_sha256': digest(args.manifest), 'audio_seconds': total,
                      'selected': {s: [r['id'] for r in samples if r['subset'] == s] for s in SUBSETS}}))


def load_controller(args):
    import numpy as np
    import torch
    loader = args.check_source / 'scripts/remote/check_component.py'
    if digest(loader) != 'da9602cf09f30e42cdd9b7f43fd81b7519255bf0eb0161bc4af0372efe0e1901':
        raise ValueError('Reusable SoulX loader digest differs')
    sys.path.insert(0, str(args.check_source / 'scripts/remote'))
    upstream = args.assets / 'upstream/frozen-20261028'
    sys.path.insert(0, str(upstream / 'soulx-duplug'))
    import model.asr
    class UnusedASR:
        def __init__(self, language='en'):
            self.language = language

        def recognize(self, *args, **kwargs):
            raise AssertionError('A second ASR was called')
    original = model.asr.SensevoiceASR
    model.asr.SensevoiceASR = UnusedASR
    from check_component import load_soulx
    try:
        controller, checks = load_soulx(args.assets, upstream, args.output)
    finally:
        model.asr.SensevoiceASR = original
    with torch.inference_mode():
        for _ in range(3):
            try:
                controller.process(np.zeros(2560, dtype=np.float32))
            except AssertionError:
                controller.reset()
    return controller, checks


def run(args):
    import numpy as np
    import soundfile as sf
    import soxr
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.35, 0)
    manifest = json.loads(args.manifest.read_text())
    samples = manifest['samples']
    if (len(samples) != 30 or Counter(s['subset'] for s in samples) !=
            Counter({s: spec[1] for s, spec in SUBSETS.items()}) or
            sum(s['duration_seconds'] for s in samples) > 1200):
        raise ValueError('Invalid frozen sample inventory')
    args.output.mkdir(exist_ok=False)
    (args.output / 'input_manifest.json').write_bytes(args.manifest.read_bytes())
    result = {'passed': False, 'cases': [], 'sensevoice_loaded': False,
              'manifest_sha256': digest(args.manifest), 'tail_seconds_added': 0,
              'nemotron_revision': 'ebe59e5a817142986528bbbee5dba8db7b38ed50',
              'soulx_revision': '61701c4ab8193cc1ee2220d3848872ac6c720142',
              'scope': 'frontend token probe only; no LLM, TTS, or active playback'}
    try:
        controller, result['checkpoint_checks'] = load_controller(args)
        for sample in samples:
            case_id = sample['case_id']
            try:
                path = Path(sample['input'])
                for name, expected in sample['files'].items():
                    if digest(path.parent / name) != expected:
                        raise ValueError(f'Frozen file changed: {path.parent / name}')
                audio, rate = sf.read(path, dtype='float32')
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                if rate != 16000:
                    audio = soxr.resample(audio, rate, 16000)
                rms = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
                peak = float(np.max(np.abs(audio)))
                gain = min(.05 / rms, .9 / peak) if rms > 0 and peak > 0 else 1.
                controller.reset()
                record = run_case(controller, (audio * gain).astype(np.float32), case_id, args.socket, args.output)
                record.update(gain=float(gain), native_rate=rate, native_rms=float(rms), native_peak=peak)
            except Exception as exc:
                record = {'case_id': case_id, 'passed': False, 'error': f'{type(exc).__name__}: {exc}',
                          'traceback': traceback.format_exc()}
                traceback.print_exc()
                if isinstance(exc, torch.cuda.OutOfMemoryError):
                    raise
            result['cases'].append(record)
            write_json(args.output / 'progress.json', result)
            print(json.dumps({k: v for k, v in record.items() if k != 'audio_metrics'}), flush=True)
        result['passed'] = len(result['cases']) == 30 and all(c['passed'] for c in result['cases'])
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        result['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        write_json(args.output / 'result.json', result)
    if not result['passed']:
        raise SystemExit(1)


def word_errors(reference, hypothesis):
    def words(text):
        return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", text.lower().replace('’', "'"))
    ref, hyp = words(reference), words(hypothesis)
    # Cells carry cost, substitutions, deletions, and insertions. Ties prefer
    # substitutions, then deletions, so the decomposition is reproducible.
    previous = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i, a in enumerate(ref, 1):
        current = [(i, 0, i, 0)]
        for j, b in enumerate(hyp, 1):
            if a == b:
                current.append(previous[j - 1])
            else:
                candidates = []
                for old, column in ((previous[j - 1], 1), (previous[j], 2), (current[-1], 3)):
                    v = list(old)
                    v[0] += 1
                    v[column] += 1
                    candidates.append(tuple(v))
                current.append(min(candidates, key=lambda v: v[0]))
        previous = current
    errors, subs, deletes, inserts = previous[-1]
    return {'reference_words': len(ref), 'errors': errors, 'substitutions': subs,
            'deletions': deletes, 'insertions': inserts, 'wer': errors / len(ref) if ref else None}


def analyze_case(sample, record, events, output):
    texts = {e['asr_version']: e['text'] for e in events if e['kind'] == 'user_transcript'}
    byid = {e['event_id']: e for e in events}
    states = [e for e in events if e['kind'] == 'user_state']
    rows, violations = [], []
    prior = None
    for state in states:
        basis = state['basis']
        control = byid[basis['control_event_id']]
        consumed = basis['consumed_asr_version']
        watermark = control['consumed_source_observed_until']
        if (consumed != control['consumed_asr_version'] or control['event_seq'] >= state['event_seq'] or
                (watermark is not None and watermark > control['audio_observed_until'])):
            violations.append(state['event_seq'])
        row = {'event_seq': state['event_seq'], 'processed_seconds': state['processed_until'] / 16000,
               'observed_seconds': basis['audio_observed_until'] / 16000,
               'controller_generation': state['controller_generation'], 'token': state['token'],
               'token_id': state['token_id'], 'raw_token': state['raw_token'],
               'raw_token_id': state['raw_token_id'], 'adjustment': state['adjustment'],
               'accepted': state['accepted'], 'context_asr_version': basis['asr_version'],
               'consumed_asr_version': consumed, 'context_text': texts[basis['asr_version']],
               'consumed_prefix': texts[consumed], 'control_text': control['control_text'],
               'transition': state['token'] != prior, 'gate_open': control['gate_open'],
               'token_replayed': control['token_replayed']}
        rows.append(row)
        prior = state['token']
    if rows:
        with (output / (sample['case_id'] + '.trace.csv')).open('w') as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    accepted = [r for r in rows if r['accepted']]
    complete = [r for r in accepted if r['token'] == '<|user_complete|>']
    summary = {'case_id': sample['case_id'], 'task': sample['task'], 'subset': sample['subset'],
               'id': sample['id'], 'passed': record['passed'], 'duration_seconds': sample['duration_seconds'],
               'reference': sample['reference'], 'annotation': sample['annotation'],
               'online_text': record.get('online_text'), 'drained_text': record.get('drained_text'),
               'error': record.get('error'), 'states': dict(Counter(r['token'] for r in rows)),
               'adjustments': sum(bool(r['adjustment']) for r in rows), 'contract_violations': violations,
               'complete': complete, 'last_control': rows[-1] if rows else None,
               'max_consumed_asr_version': max((r['consumed_asr_version'] for r in rows), default=0),
               'token_replays': record.get('token_replays'), 'event_sha256': None}
    if sample['reference'] is not None and record.get('online_text') is not None:
        summary['word_errors'] = word_errors(sample['reference'], record['online_text'])
    def boundary_metrics(boundary, start=0):
        selected = [r for r in complete if r['processed_seconds'] >= start]
        later = [r for r in selected if r['processed_seconds'] >= boundary]
        return {'boundary_seconds': boundary,
                'complete_before_boundary': [r for r in selected if r['processed_seconds'] < boundary],
                'complete_observed_before_boundary': [r for r in selected if r['observed_seconds'] < boundary],
                'complete_more_than_160ms_early': [r for r in selected if r['processed_seconds'] < boundary - .16],
                'complete_at_or_after_boundary': later,
                'first_later_delay_seconds': later[0]['processed_seconds'] - boundary if later else None}
    if sample['task'] == 'smooth_turn_taking':
        summary['turn_end'] = boundary_metrics(sample['annotation'][0]['timestamp'][0])
    elif sample['task'] == 'pause_handling':
        pauses = []
        for annotation in sample['annotation']:
            start, end = annotation['timestamp']
            inside = [r for r in accepted if start <= r['processed_seconds'] < end]
            pauses.append({'start': start, 'end': end, 'complete': [r for r in inside if r['token'] == '<|user_complete|>'],
                           'complete_observed_inside': [r for r in complete if start <= r['observed_seconds'] < end],
                           'tokens': dict(Counter(r['token'] for r in inside))})
        summary['pauses'] = pauses
        transcription = sample.get('reference')
        summary['reference_available'] = transcription is not None
        if sample.get('reference_end_seconds') is not None:
            summary['turn_end'] = boundary_metrics(sample['reference_end_seconds'])
    else:
        start, end = sample['annotation'][0]['timestamp']
        nonidle = [r for r in accepted if r['token'] == '<|user_nonidle|>' and start <= r['processed_seconds'] <= end]
        transitions = [r for r in nonidle if r['transition']]
        summary['interruption'] = {'start': start, 'end': end,
                                   'first_nonidle': nonidle[0] if nonidle else None,
                                   'first_nonidle_transition': transitions[0] if transitions else None,
                                   'nonidle_delay_seconds': nonidle[0]['processed_seconds'] - start if nonidle else None}
        # Completion of the initial context question is legitimate and must
        # not be scored as premature completion of the later interruption.
        summary['turn_end'] = boundary_metrics(end, start)
    return summary


def analyze(args):
    args.output.mkdir(exist_ok=False, parents=True)
    manifest = json.loads((args.probe / 'input_manifest.json').read_text())
    results = {c['case_id']: c for c in json.loads((args.probe / 'result.json').read_text())['cases']}
    summaries = []
    for sample in manifest['samples']:
        path = args.probe / (sample['case_id'] + '.events.jsonl')
        events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        summary = analyze_case(sample, results.get(sample['case_id'], {'passed': False, 'error': 'not run'}),
                               events, args.output)
        summary['event_sha256'] = digest(path) if path.exists() else None
        summaries.append(summary)
    groups = {}
    for task in ('smooth_turn_taking', 'pause_handling', 'user_interruption'):
        rows = [r for r in summaries if r['task'] == task]
        group = {'samples': len(rows), 'passed': sum(r['passed'] for r in rows),
                 'samples_with_complete': sum(bool(r['complete']) for r in rows),
                 'complete_events': sum(len(r['complete']) for r in rows)}
        if task != 'pause_handling':
            for key in ('complete_before_boundary', 'complete_observed_before_boundary',
                        'complete_more_than_160ms_early', 'complete_at_or_after_boundary'):
                group['samples_with_' + key] = sum(bool(r['turn_end'][key]) for r in rows)
            if task == 'user_interruption':
                group['samples_with_nonidle_during_interruption'] = sum(r['interruption']['first_nonidle'] is not None for r in rows)
                group['samples_with_new_nonidle_transition'] = sum(r['interruption']['first_nonidle_transition'] is not None for r in rows)
        else:
            group['pause_intervals'] = sum(len(r['pauses']) for r in rows)
            group['samples_with_complete_during_pause'] = sum(any(p['complete'] for p in r['pauses']) for r in rows)
            group['pause_intervals_with_complete'] = sum(bool(p['complete']) for r in rows for p in r['pauses'])
            group['pause_intervals_with_complete_observed_inside'] = sum(bool(p['complete_observed_inside']) for r in rows for p in r['pauses'])
            group['samples_with_complete_after_last_reference_word'] = sum(bool(r.get('turn_end', {}).get('complete_at_or_after_boundary')) for r in rows)
        word_scores = [r['word_errors'] for r in rows if 'word_errors' in r]
        group['samples_with_reference'] = len(word_scores)
        if word_scores:
            n = sum(v['reference_words'] for v in word_scores)
            e = sum(v['errors'] for v in word_scores)
            group.update(reference_words=n, word_errors=e, micro_wer=e / n if n else None)
        groups[task] = group
    write_json(args.output / 'analysis.json', {'groups': groups, 'samples': summaries,
                                               'manifest_sha256': digest(args.probe / 'input_manifest.json')})
    print(json.dumps(groups, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('freeze')
    prepare.add_argument('--input', type=Path, required=True)
    prepare.add_argument('--manifest', type=Path, required=True)
    prepare.add_argument('--seed', type=int, default=20261030)
    infer = commands.add_parser('run')
    for name in ('manifest', 'assets', 'check-source', 'socket', 'output'):
        infer.add_argument('--' + name, type=Path, required=True)
    inspect = commands.add_parser('analyze')
    inspect.add_argument('--probe', type=Path, required=True)
    inspect.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    {'freeze': freeze, 'run': run, 'analyze': analyze}[args.command](args)


if __name__ == '__main__':
    main()
