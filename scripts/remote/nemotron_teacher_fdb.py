"""Replay frozen FDB inputs with synchronized RNNT teacher forcing and audit."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import socket
import sys
import threading
import time
import traceback
import re

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from nemotron_teacher_frontend import NemotronTeacherFrontend

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

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
    return controller, checks


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

def rpc(path, operation, **payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(path))
        connection.sendall(json.dumps(dict(operation=operation, **payload)).encode() + b'\n')
        response = json.loads(connection.makefile('rb').readline(4 * 1024 * 1024))
    if 'error' in response:
        raise RuntimeError(response['error'])
    return response


class AudioProgressPairing:
    """Pair by arrived PCM coverage while keeping native and teacher steps separate."""

    def __init__(self):
        self.native_seq = self.teacher_seq = self.observed_end = self.next_end = 0

    def accept(self, step, target_end):
        if step['step_seq'] != self.native_seq + 1 or step['eof_received']:
            raise ValueError('Unordered or drained native step in online pairing')
        end = step['feature_end_sample']
        if (step['consumed_samples'] != end or end > step['received_samples']
                or end <= self.observed_end or step['next_feature_end_sample'] <= end):
            raise ValueError('Invalid native PCM coverage')
        if self.next_end and end != self.next_end:
            raise ValueError('Native feature window differs from announced next window')
        if target_end != (self.teacher_seq + 1) * 2560:
            raise ValueError('Teacher audio target skipped or duplicated')
        startup = end < target_end
        if startup and (self.native_seq != 0 or self.teacher_seq != 0):
            raise ValueError('Only the first short native chunk may precede a teacher step')
        if not startup and self.observed_end >= target_end:
            raise ValueError('Pairing skipped an earlier sufficient native window')
        self.native_seq, self.observed_end = step['step_seq'], end
        self.next_end = step['next_feature_end_sample']
        if not startup:
            self.teacher_seq += 1
        return 'startup' if startup else 'context'


def run_case(model, audio, case_id, path, output, empty_nonidle_rule=True):
    import numpy as np
    import torch
    identity = rpc(path, 'create')['session_id']
    frontend = NemotronTeacherFrontend(model, case_id, empty_nonidle_rule=empty_nonidle_rule)
    stopped = threading.Event()
    arrived = threading.Condition()
    state = {'end': 0, 'eof': False, 'error': None}
    ledger, buffer, base = [], np.empty(0, dtype=np.float32), 0
    back_size = model.config.infer_config.input.audio_back_size
    ahead_size = model.config.infer_config.input.audio_ahead_size
    started = time.monotonic()

    def feed():
        nonlocal buffer
        try:
            for start in range(0, len(audio), 1280):
                end = min(start + 1280, len(audio))
                if stopped.wait(max(0, started + end / 16000 - time.monotonic())):
                    return
                pcm = (np.clip(audio[start:end], -1, 1) * 32767).astype('<i2').tobytes()
                rpc(path, 'push', session_id=identity, audio=base64.b64encode(pcm).decode())
                with arrived:
                    buffer = np.concatenate((buffer, np.frombuffer(pcm, '<i2').astype(np.float32) / 32768))
                    state['end'] = end
                    if end - len(ledger) * 2560 > 12800:
                        raise RuntimeError('SoulX audio backlog exceeded 800ms')
                    arrived.notify_all()
            with arrived:
                state['eof'] = True
                arrived.notify_all()
        except Exception:
            with arrived:
                state['error'] = traceback.format_exc()
                arrived.notify_all()

    reader = threading.Thread(target=feed, daemon=True)
    reader.start()
    pairing = AudioProgressPairing()
    seq, pending_step = 0, None
    startup_steps = []
    previous_released_at = None
    file = (output / f'{case_id}.frames.jsonl').open('x')
    startup_file = (output / f'{case_id}.startup.jsonl').open('x')
    try:
        while True:
            begin, end = seq * 2560, (seq + 1) * 2560
            with arrived:
                required_end = max(end + ahead_size, pairing.next_end)
                while state['end'] < required_end and not state['eof'] and not state['error']:
                    arrived.wait(.05)
                if state['error']:
                    raise RuntimeError(state['error'])
                if state['end'] < required_end:
                    break
                if state['end'] - begin > 12800:
                    raise RuntimeError('Teacher processing backlog exceeded 800ms')
                back_start = max(0, begin - back_size)
                back = np.pad(buffer[back_start - base:begin - base].copy(),
                              (max(0, back_size - begin), 0))
                chunk = buffer[begin - base:end - base].copy()
                ahead = buffer[end - base:end + ahead_size - base].copy()
            while pending_step is None:
                if state['error']:
                    raise RuntimeError(state['error'])
                batch = rpc(path, 'poll', session_id=identity, after=pairing.native_seq)
                if batch['steps']:
                    if len(batch['steps']) != 1:
                        raise AssertionError('ASR decoded beyond its publication barrier')
                    pending_step = batch['steps'][0]
                    break
                if time.monotonic() - (started + end / 16000) > .8:
                    raise RuntimeError('ASR completion backlog exceeded 800ms')
                stopped.wait(.002)
            step = pending_step
            kind = pairing.accept(step, end)
            if previous_released_at is not None and step['decode_started_at'] < previous_released_at:
                raise AssertionError('ASR advanced before its preceding barrier release')
            if kind == 'startup':
                startup = {'native_step': step, 'startup_recorded_at': time.monotonic()}
                startup_file.write(json.dumps(startup, ensure_ascii=False) + '\n')
                startup_file.flush()
                release = rpc(path, 'release', session_id=identity, step_seq=step['step_seq'],
                              published_at=startup['startup_recorded_at'], publication_kind='startup')
                startup_steps.append(dict(startup, **release))
                previous_released_at = release['released_at']
                pending_step = None
                continue
            observed = max(end + ahead_size, step['consumed_samples'])
            with arrived:
                if step['consumed_samples'] > state['end']:
                    raise AssertionError('ASR observation exceeds arrived PCM')
            with torch.inference_mode():
                frame = frontend.process_step(dict(step, step_seq=seq + 1), chunk, back, ahead, end, observed)
            frame.update(native_step=step, teacher_step_seq=seq + 1, pairing_mode='audio_coverage',
                         asr_observation_ahead_ms=(step['consumed_samples'] - end) / 16)
            if not (step['decode_completed_at'] <= frame['controller_started_at'] <= frame['teacher_injected_at']
                    <= frame['state_resolved_at'] <= frame['published_at']):
                raise AssertionError('Teacher publication order is invalid')
            backlog_ms = (time.monotonic() - started - end / 16000) * 1000
            if backlog_ms > 800:
                raise RuntimeError('Joint publication backlog exceeded 800ms')
            release = rpc(path, 'release', session_id=identity, step_seq=step['step_seq'],
                          published_at=frame['published_at'])
            frame.update(release, backlog_ms=backlog_ms,
                         observed_backlog_ms=backlog_ms - (observed - end) / 16)
            previous_released_at = release['released_at']
            ledger.append(frame)
            file.write(json.dumps(frame, ensure_ascii=False) + '\n')
            file.flush()
            seq += 1
            pending_step = None
            with arrived:
                retain = max(0, end - back_size)
                buffer = buffer[retain - base:]
                base = retain
        reader.join(2)
        if reader.is_alive() or state['error']:
            raise RuntimeError(state['error'] or 'Ingress failed to terminate')
        pending_tail = {'available_token_ids': frontend.available_ids, 'consumed_token_ids': frontend.teacher_ids,
                        'pending_token_range': ledger[-1]['pending_token_range'] if ledger else [0, 0],
                        'control_text': frontend.control_text}
        online = frontend.close()['text']
        rpc(path, 'push', session_id=identity, eof=True)
        deadline = time.monotonic() + 10
        while True:
            batch = rpc(path, 'poll', session_id=identity, after=pairing.native_seq)
            if batch['ended']:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('ASR EOF drain exceeded ten seconds')
            stopped.wait(.01)
        drained = batch['steps'][-1]['text'] if batch['steps'] else online
        return {'case_id': case_id, 'passed': True, 'online_text': online, 'drained_text': drained,
                'teacher_tail': pending_tail,
                'gate_open_frames': sum(f['gate_open'] for f in ledger),
                'pending_frames': sum(f['pending_token_range'][0] < f['pending_token_range'][1] for f in ledger),
                'cache_rebuilds': frontend.rebuilds, 'cache_replay_tokens': frontend.replay_tokens,
                'cache_replay_seconds': sum(f['cache_revision'].get('replay_seconds', 0) for f in ledger),
                'frames': len(ledger), 'real_samples': len(audio), 'processed_samples': seq * 2560,
                'pairing_mode': 'audio_coverage', 'startup_steps': startup_steps,
                'last_online_native_step': pairing.native_seq,
                'pending_real_samples': len(audio) - seq * 2560,
                'state_counts': dict(Counter(v['state_token'] for v in ledger)),
                'raw_state_counts': dict(Counter(v['raw_token'] for v in ledger)),
                'adjustments': dict(Counter(v['adjustment'] for v in ledger if v['adjustment'])),
                'rejected_states': sum(not v['state_accepted'] for v in ledger),
                'max_backlog_ms': max((v['backlog_ms'] for v in ledger), default=0),
                'elapsed_seconds': time.monotonic() - started}
    finally:
        stopped.set()
        reader.join(3)
        frontend.kv, frontend.checkpoint = None, None
        frontend.entries.clear()
        file.close()
        startup_file.close()
        rpc(path, 'close', session_id=identity)
        if reader.is_alive():
            raise RuntimeError('Ingress thread did not terminate')


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
    if len(samples) != 30 or sum(s['duration_seconds'] for s in samples) > 1200:
        raise ValueError('Expected the frozen thirty-clip FDB manifest')
    if args.smoke:
        samples = [next(s for s in samples if s['task'] == task)
                   for task in ('smooth_turn_taking', 'pause_handling', 'user_interruption')]
    args.output.mkdir(exist_ok=False)
    write_json(args.output / 'input_manifest.json', dict(manifest, samples=samples))
    result = {'passed': False, 'cases': [], 'teacher_forcing': True, 'timing_mode': 'realtime',
              'pairing_mode': 'audio_coverage', 'control_mode': 'official_format_gated_teacher',
              'cache_limits': {'sequence_tokens': 8192, 'rebuilds': 128, 'replay_tokens': 65536},
              'sensevoice_loaded': False, 'empty_nonidle_rule': not args.disable_empty_rule,
              'manifest_sha256': digest(args.manifest),
              'source_commit': __import__('os').environ.get('SOULX_SOURCE_COMMIT'),
              'nemotron_revision': 'ebe59e5a817142986528bbbee5dba8db7b38ed50',
              'soulx_revision': '61701c4ab8193cc1ee2220d3848872ac6c720142'}
    try:
        controller, result['checkpoint_checks'] = load_controller(args)
        # Exercise the real forced-input path before the clock starts.
        warm = NemotronTeacherFrontend(controller, 'warmup')
        with torch.inference_mode():
            for seq in range(1, 4):
                warm.process_step({'step_seq': seq, 'text': ''}, np.zeros(2560, np.float32),
                                  np.zeros(controller.config.infer_config.input.audio_back_size, np.float32),
                                  np.zeros(controller.config.infer_config.input.audio_ahead_size, np.float32),
                                  seq * 2560, seq * 2560)
        warm.close()
        torch.cuda.synchronize()
        for sample in samples:
            try:
                path = Path(sample['input'])
                for name, expected in sample['files'].items():
                    if digest(path.parent / name) != expected:
                        raise ValueError(f'Frozen input digest differs: {path.parent / name}')
                audio, rate = sf.read(path, dtype='float32')
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                if rate != 16000:
                    audio = soxr.resample(audio, rate, 16000)
                rms, peak = np.sqrt(np.mean(audio.astype(np.float64) ** 2)), float(np.max(np.abs(audio)))
                gain = min(.05 / rms, .9 / peak) if rms > 0 and peak > 0 else 1.
                record = run_case(controller, (audio * gain).astype(np.float32), sample['case_id'],
                                  args.socket, args.output, not args.disable_empty_rule)
                record['gain'] = float(gain)
            except Exception as exc:
                record = {'case_id': sample['case_id'], 'passed': False,
                          'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()}
                traceback.print_exc()
            result['cases'].append(record)
            write_json(args.output / 'progress.json', result)
            print(json.dumps(record, ensure_ascii=False), flush=True)
        result['passed'] = all(v['passed'] for v in result['cases']) and len(result['cases']) == len(samples)
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        result['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        write_json(args.output / 'result.json', result)
    if not result['passed']:
        raise SystemExit(1)


def analyze(args):
    args.output.mkdir(exist_ok=False, parents=True)
    manifest = json.loads((args.probe / 'input_manifest.json').read_text())
    result = json.loads((args.probe / 'result.json').read_text())
    records = {v['case_id']: v for v in result['cases']}
    summaries = []
    for sample in manifest['samples']:
        record = records.get(sample['case_id'], {'passed': False})
        path = args.probe / (sample['case_id'] + '.frames.jsonl')
        frames = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        accepted = [v for v in frames if v['state_accepted']]
        complete = [v for v in accepted if v['state_token'] == '<|user_complete|>']
        summary = dict(sample, **{k: v for k, v in record.items() if k != 'case_id'})
        summary['complete'] = complete
        if sample['reference'] is not None and record.get('online_text') is not None:
            summary['word_errors'] = word_errors(sample['reference'], record['online_text'])
            summary['drained_word_errors'] = word_errors(sample['reference'], record['drained_text'])
        if sample['task'] == 'pause_handling':
            summary['pause_intervals'] = [dict(start=a['timestamp'][0], end=a['timestamp'][1],
                complete_count=sum(a['timestamp'][0] <= f['processed_until'] / 16000 < a['timestamp'][1] for f in complete),
                observed_complete_count=sum(a['timestamp'][0] <= f['audio_observed_until'] / 16000 < a['timestamp'][1] for f in complete))
                for a in sample['annotation']]
        else:
            boundary = sample['annotation'][0]['timestamp'][0 if sample['task'] == 'smooth_turn_taking' else 1]
            start = 0 if sample['task'] == 'smooth_turn_taking' else sample['annotation'][0]['timestamp'][0]
            relevant = [f for f in complete if f['processed_until'] / 16000 >= start]
            summary['boundary_before_complete'] = [f for f in relevant if f['processed_until'] / 16000 >= boundary]
            summary['premature_complete'] = [f for f in relevant if f['processed_until'] / 16000 < boundary]
            summary['observed_premature_complete'] = [f for f in relevant if f['audio_observed_until'] / 16000 < boundary]
            summary['more_than_160ms_early'] = [f for f in relevant if f['processed_until'] / 16000 < boundary - .16]
            if sample['task'] == 'user_interruption':
                nonidle = [f for f in accepted if f['state_token'] == '<|user_nonidle|>' and start <= f['processed_until'] / 16000 <= boundary]
                summary['nonidle_delay_ms'] = (nonidle[0]['processed_until'] / 16000 - start) * 1000 if nonidle else None
        if frames:
            columns = ['processed_until', 'audio_observed_until', 'text', 'delta_text', 'raw_token',
                       'state_token', 'state_accepted', 'adjustment', 'teacher_char_end',
                       'teacher_injected_at', 'state_resolved_at', 'published_at', 'released_at', 'backlog_ms',
                       'step_seq', 'teacher_step_seq', 'pairing_mode', 'asr_observation_ahead_ms',
                       'observed_backlog_ms']
            with (args.output / (sample['case_id'] + '.trace.csv')).open('w') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(frames)
        summaries.append(summary)
    groups = {}
    for task in ('smooth_turn_taking', 'pause_handling', 'user_interruption'):
        rows = [r for r in summaries if r['task'] == task]
        group = {'samples': len(rows), 'passed': sum(r['passed'] for r in rows),
                 'complete_events': sum(len(r['complete']) for r in rows)}
        for key in ('boundary_before_complete', 'premature_complete', 'observed_premature_complete', 'more_than_160ms_early'):
            if task != 'pause_handling':
                group['samples_with_' + key] = sum(bool(r.get(key)) for r in rows)
        if task == 'pause_handling':
            pauses = [p for r in rows for p in r['pause_intervals']]
            group.update(pause_intervals=len(pauses), pause_intervals_with_complete=sum(p['complete_count'] > 0 for p in pauses),
                         pause_intervals_with_observed_complete=sum(p['observed_complete_count'] > 0 for p in pauses))
        if task == 'user_interruption':
            group['nonidle_delays_ms'] = [r['nonidle_delay_ms'] for r in rows if r.get('nonidle_delay_ms') is not None]
        for key, prefix in (('word_errors', 'online'), ('drained_word_errors', 'drained')):
            scores = [r[key] for r in rows if key in r]
            words = sum(s['reference_words'] for s in scores)
            errors = sum(s['errors'] for s in scores)
            group[prefix + '_wer'] = errors / words if words else None
            group[prefix + '_reference_words'] = words
            group[prefix + '_word_errors'] = errors
        groups[task] = group
    write_json(args.output / 'analysis.json', {'groups': groups, 'samples': summaries,
                                               'manifest_sha256': digest(args.probe / 'input_manifest.json')})
    print(json.dumps(groups, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    infer = commands.add_parser('run')
    for name in ('manifest', 'assets', 'check-source', 'socket', 'output'):
        infer.add_argument('--' + name, type=Path, required=True)
    infer.add_argument('--disable-empty-rule', action='store_true')
    infer.add_argument('--smoke', action='store_true')
    inspect = commands.add_parser('analyze')
    inspect.add_argument('--probe', type=Path, required=True)
    inspect.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    {'run': run, 'analyze': analyze}[args.command](args)


if __name__ == '__main__':
    main()
