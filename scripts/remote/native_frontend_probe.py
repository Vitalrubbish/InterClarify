"""Run the frozen NTF-018 warmup matrix and real-clock three-axis gate."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import gzip
import json
from pathlib import Path
import random
import sys
import threading
import time
import traceback

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from dual_audio import DualAudioFrontend, PCMLedger
from native_soulx import NativeSoulX, pcm_digest
from native_soulx_loader import load_native_controller
from shared_context import SharedContext
from native_frontend_worker import X2Process
from x2_streaming_probe import digest, distribution, load_audio, write_json

ROOT = Path(__file__).parents[2]
MANIFEST_SHA256 = '403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07'
WARMUP_SHA256 = 'd733a878fbb3393dac0349cfa1293e4fad9a8bd5ec1f58ce6adc019de4b94f32'
PREFLIGHT = ['candor_turn_taking-102', 'candor_pause_handling-127', 'synthetic_user_interruption-104']
LENGTHS = [25600, 51200, 53760, 107520, 161280]


def seed_all():
    import torch
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)


def quantize(audio):
    return (np.clip(audio, -1, 1) * 32767).astype('<i2').astype(np.float32) / 32768


def prepare_warmup(audio):
    values = np.asarray(audio, dtype=np.float32)
    if values.shape != (124800,) or not np.isfinite(values).all():
        raise ValueError('Expected finite 7.8 second mono warmup speech')
    rms = float(np.sqrt(np.mean(values.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(values)))
    if not rms or not peak:
        raise ValueError('Warmup speech cannot be silent')
    gain = min(.05 / rms, .9 / peak)
    speech = quantize((values * gain).astype(np.float32))
    if np.max(np.abs(speech)) < .02:
        raise ValueError('Warmup speech never reaches the frozen far-field threshold')
    output = np.concatenate((speech, np.zeros(25600, np.float32)))
    evidence = {'policy': 'rms_005_peak_09_pcm16_v2', 'original_rms': rms,
                'original_peak': peak, 'gain': gain, 'prepared_peak': float(np.max(np.abs(speech))),
                'prepared_rms': float(np.sqrt(np.mean(speech.astype(np.float64) ** 2))),
                'speech_sha256': pcm_digest(speech)}
    return output, evidence


def warmup_audio(path):
    import soundfile as sf
    import soxr
    if digest(path) != WARMUP_SHA256:
        raise ValueError('Frozen warmup audio digest differs')
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        audio = soxr.resample(audio, rate, 16000)
    if len(audio) != 124800:
        raise ValueError('Expected 7.8 seconds of fixed speech')
    return prepare_warmup(audio)


class SingleLane:
    """Reference only native control, with the same arrival and PCM limits."""

    def __init__(self, controller, realtime=True):
        self.controller, self.realtime = controller, realtime
        self.ledger = PCMLedger()
        self.lock = threading.RLock()
        self.started_at, self.step_id, self.closed = None, 0, False
        self.completed_until = 0
        controller.reserve_pcm = self.reserve

    def reserve(self, additional):
        if self.ledger.nbytes + self.controller.pcm_bytes() + additional > 4 * 2**20:
            raise MemoryError('Single-lane PCM would exceed 4 MiB')

    def check(self):
        self.reserve(0)

    def append_pcm(self, audio):
        with self.lock:
            if self.closed:
                raise RuntimeError('Single-lane reference is closed')
            self.reserve(audio.nbytes)
            packet = self.ledger.append(audio)
            if self.started_at is None:
                self.started_at = time.monotonic() - self.ledger.end / 16000
            self.check()
            return packet

    def finish_input(self):
        self.ledger.finish()

    def advance(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('Single-lane reference is closed')
            self.check()
            if self.ledger.eof and self.step_id * 2560 >= self.ledger.end:
                return None
            required = self.controller.submitted_until + 2560
            if self.ledger.end < required and not self.ledger.eof:
                return None
            ready_at = self.ledger.ready_at(required)
        receipt = self.controller.step(self.ledger, self.step_id)
        with self.lock:
            self.completed_until = receipt['processed_until']
            self.check()
            self.step_id += 1
            self.ledger.discard_before(self.controller.processed_until)
        return {'step_id': receipt['step_id'], 'input_ready_at': ready_at,
                'receipts': {'controller': receipt}, 'released_at': time.monotonic()}

    def close(self):
        with self.lock:
            self.closed = True
        self.controller.cancel()

    def diagnostics(self):
        return {'input_end': self.ledger.end, 'input_eof': self.ledger.eof,
                'processed_until': self.controller.processed_until,
                'unprocessed_real_samples': self.ledger.end - self.controller.processed_until,
                'controller_events': deepcopy(self.controller._events),
                'pcm_bytes': self.ledger.nbytes + self.controller.pcm_bytes()}


def fresh(model, worker, identity, realtime, order):
    import torch
    seed_all()
    model.reset()
    controller = NativeSoulX(model, synchronize=torch.cuda.synchronize, profile=True,
                             session_id=identity, turn_id='input')
    if worker is None:
        frontend = SingleLane(controller, realtime)
        return frontend, None
    asr = worker.session(identity, 'input')
    context = SharedContext()
    context.open_user_turn(identity, 'input', 'x2_streaming_asr')
    frontend = DualAudioFrontend(controller, asr, context=context, realtime=realtime, order=order, concurrent=True)
    return frontend, context


def cleanup(frontend, worker):
    import torch
    frontend.close()
    frontend.controller.on_state = None
    frontend.controller.detach()
    model = frontend.controller.model
    seed_all()
    model.reset()
    torch.cuda.synchronize()
    record = {'native_kv_cleared': model.past_state is None,
              'native_history_cleared': not model.history_chunks,
              'native_speech_cleared': not model.speech_detected,
              'callbacks_detached': not hasattr(model, '_native'),
              'native_buffer_samples': [len(getattr(model, name)) for name in ('buffer', 'buffer_for_asr', 'cascade_buffer')],
              'reset_buffer_sha256': pcm_digest(model.buffer)}
    if worker is not None:
        record['x2'] = worker.request('clear')
    return record


def replay(model, worker, audio, identity, output, realtime, order=('controller', 'asr'), compress=False):
    frontend, context = fresh(model, worker, identity, realtime, order)
    stopped = threading.Event()
    ingress_errors, arrivals, rows = [], [], []
    started = time.monotonic()
    frontend.started_at = started

    def feed():
        try:
            for begin in range(0, len(audio), 1280):
                end = min(begin + 1280, len(audio))
                due = started + end / 16000
                if stopped.wait(max(0, due - time.monotonic())):
                    return
                at = time.monotonic()
                packet = frontend.append_pcm(audio[begin:end])
                arrivals.append(dict(packet, due_at=due, late_ms=(at - due) * 1000))
            frontend.finish_input()
        except Exception:
            ingress_errors.append(traceback.format_exc())
            stopped.set()
            frontend.close()

    reader = threading.Thread(target=feed, name='pcm-arrival', daemon=True) if realtime else None
    result = {'case_id': identity, 'passed': False, 'timing_mode': 'realtime' if realtime else 'warmup',
              'audio_sha256': pcm_digest(audio), 'real_samples': len(audio), 'lane_order': list(order) if worker else ['controller'],
              'lane_execution': 'concurrent' if worker else 'single', 'started_at': started}
    cursor = 0
    previous_release = 0.
    try:
        if reader:
            reader.start()
        path = output / f'{identity}.frames.jsonl'
        stream = gzip.open(str(path) + '.gz', 'xt', encoding='utf-8', compresslevel=1) if compress else path.open('x')
        with stream:
            while True:
                if ingress_errors:
                    raise RuntimeError(ingress_errors[0])
                if not realtime:
                    # Only supply one step and its real lookahead; warmup cannot build an unbounded queue.
                    target = min(len(audio), max(cursor, (len(rows) + 1) * 2560 + 200))
                    if target > cursor:
                        frontend.append_pcm(audio[cursor:target])
                        cursor = target
                    if cursor == len(audio) and not frontend.ledger.eof:
                        frontend.finish_input()
                row = frontend.advance()
                if row is None:
                    if frontend.ledger.eof and len(rows) * 2560 >= len(audio):
                        break
                    if realtime:
                        stopped.wait(.001)
                    continue
                controller = row['receipts']['controller']
                if controller['started_at'] < previous_release:
                    raise ValueError('Controller advanced before the previous release')
                row['pcm_bytes'] = frontend.ledger.nbytes + frontend.controller.pcm_bytes()
                row['unread_samples'] = {'controller': frontend.ledger.end - controller['processed_until']}
                state = controller['state']
                row['controller_main_lag_ms'] = (row['released_at'] - started - state['state_processed_until'] / 16000) * 1000
                row['controller_observed_lag_ms'] = (row['released_at'] - started - state['state_observed_until'] / 16000) * 1000
                if context is not None:
                    read_at = time.monotonic()
                    snapshot = context.get_user_turn(identity, 'input')
                    row.update(snapshot=snapshot, read_at=read_at)
                    frames = row['receipts']['asr']['frames']
                    if any(frame['started_at'] < previous_release for frame in frames):
                        raise ValueError('X2 advanced before the previous release')
                    if snapshot['asr_processed_until'] < snapshot['state_observed_until']:
                        raise ValueError('X2 did not cover the controller observation')
                    row['asr_main_lag_ms'] = (row['batch_published_at'] - started - frames[-1]['asr_processed_until'] / 16000) * 1000
                    row['unread_samples']['asr'] = frontend.ledger.end - frontend.asr.processed_until
                previous_release = row['released_at']
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
        expected = (len(audio) + 2559) // 2560
        result['passed'] = len(rows) == expected if context is not None else len(rows) >= expected
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        stopped.set()
        if reader:
            reader.join(3)
            if reader.is_alive():
                raise RuntimeError('PCM producer did not terminate')
        if ingress_errors:
            result.update(passed=False, ingress_error=ingress_errors[0])
        result.update(frames=len(rows), elapsed_seconds=time.monotonic() - started,
                      diagnostics=frontend.diagnostics())
        if rows and context is not None:
            result['online_text'] = rows[-1]['snapshot']['text']
        result['cleanup'] = cleanup(frontend, worker)
        if not clean_session(result['cleanup'], worker is not None):
            result.update(passed=False, cleanup_error='Session state was not fully cleared')
        result['timing'] = summarize(rows)
        result['coverage'] = coverage(rows)
        result['arrival_late_ms'] = distribution([row['late_ms'] for row in arrivals])
        write_json(output / f'{identity}.result.json', result)
    return result


def clean_session(record, dual):
    valid = all(record.get(key) is True for key in (
        'native_kv_cleared', 'native_history_cleared', 'native_speech_cleared', 'callbacks_detached'))
    valid = valid and record.get('native_buffer_samples') == [16000, 25600, 51200]
    if dual:
        valid = valid and all(record.get('x2', {}).get(key) is True for key in (
            'kv_cleared', 'text_cleared', 'callbacks_cleared', 'counters_cleared'))
    return bool(valid)


def summarize(rows):
    controller = [row['receipts']['controller'] for row in rows]
    summary = {'first_frame': rows[0] if rows else None,
               'controller_compute_ms': distribution([(row['completed_at'] - row['started_at']) * 1000 for row in controller]),
               'controller_main_lag_ms': distribution([row['controller_main_lag_ms'] for row in rows]),
               'stable_main_lag_ms': distribution([row['controller_main_lag_ms'] for row in rows[1:]]),
               'controller_observed_lag_ms': distribution([row['controller_observed_lag_ms'] for row in rows]),
               'raw_state_main_lag_ms': distribution([row['controller_main_lag_ms'] -
                    (row['released_at'] - row['receipts']['controller']['state']['state_available_at']) * 1000 for row in rows]),
               'controller_queue_ms': distribution([(row['started_at'] - rows[index]['input_ready_at']) * 1000
                                                       for index, row in enumerate(controller)]),
               'sensevoice_by_length': {}, 'controller_stages': {}, 'asr_stages': {},
               'asr_main_lag_ms': distribution([row['asr_main_lag_ms'] for row in rows if 'asr_main_lag_ms' in row]),
               'stable_asr_main_lag_ms': distribution([row['asr_main_lag_ms'] for row in rows[1:] if 'asr_main_lag_ms' in row]),
               'asr_compute_ms': distribution([(frame['completed_at'] - frame['started_at']) * 1000
                    for row in rows for frame in row['receipts'].get('asr', {}).get('frames', [])]),
               'joint_commit_ms': distribution([row['commit_seconds'] * 1000 for row in rows if 'commit_seconds' in row]),
               'state_available_to_publish_ms': distribution([(row['batch_published_at'] - row['receipts']['controller']['state']['state_available_at']) * 1000
                                                              for row in rows if 'batch_published_at' in row]),
               'eos_available_to_publish_ms': distribution([(row['batch_published_at'] - frame['text_available_at']) * 1000
                    for row in rows for frame in row['receipts'].get('asr', {}).get('frames', [])
                    if frame['decision'] == 33 and frame['text_available_at'] is not None]),
               'barrier_wait_ms': {}, 'first_text': None, 'first_encounters': []}
    for row in controller:
        for event in row['events']:
            if event['kind'] == 'sensevoice':
                count = sum(span['samples'] for span in event['spans'])
                summary['sensevoice_by_length'].setdefault(str(count), []).append((event['completed_at'] - event['started_at']) * 1000)
            if event['kind'] == 'stage':
                summary['controller_stages'].setdefault(event['name'], []).append((event['completed_at'] - event['started_at']) * 1000)
    seen = set()
    for row in rows:
        if 'snapshot' not in row:
            continue
        if row['snapshot']['text'] and summary['first_text'] is None:
            summary['first_text'] = {'step_id': row['step_id'], 'snapshot': row['snapshot'], 'read_at': row['read_at']}
        for lane, seconds in row['wait_seconds'].items():
            summary['barrier_wait_ms'].setdefault(lane, []).append(seconds * 1000)
        for frame in row['receipts']['asr']['frames']:
            for stage in frame.get('stages', []):
                summary['asr_stages'].setdefault(stage['name'], []).append((stage['completed_at'] - stage['started_at']) * 1000)
    for row in rows:
        for event in row['receipts']['controller']['events']:
            key = (event['kind'], event.get('state_token'), event.get('needed'),
                   sum(span['samples'] for span in event.get('spans', [])))
            if key not in seen:
                seen.add(key)
                summary['first_encounters'].append({'step_id': row['step_id'], 'event': event,
                    'controller_main_lag_ms': row['controller_main_lag_ms']})
    for field in ('sensevoice_by_length', 'controller_stages', 'asr_stages', 'barrier_wait_ms'):
        summary[field] = {name: distribution(values) for name, values in summary[field].items()}
    return summary


def coverage(rows):
    events = [event for row in rows for event in row['receipts']['controller']['events']]
    frames = [frame for row in rows for frame in row['receipts'].get('asr', {}).get('frames', [])]
    return {'sensevoice_text': any(event['kind'] == 'sensevoice' and event['control_text'].strip() for event in events),
            'text_revision': any(event['kind'] == 'text_revision' and event['needed'] for event in events),
            'native_complete': any(row['receipts']['controller']['service_completion_source'] == 'model_complete' for row in rows),
            'reset': any(event['kind'] == 'reset' for event in events),
            'wait': any(frame['decision'] == 32 for frame in frames),
            'multi_token_eos': any(len(frame.get('decode', {}).get('token_ids', [])) >= 4 for frame in frames),
            'joint_complete': any(row.get('snapshot', {}).get('state_token') == '<|user_complete|>'
                                  and row['snapshot']['state_accepted'] for row in rows),
            'joint_wait': any('snapshot' in row and all(frame['decision'] == 32 for frame in row['receipts']['asr']['frames']) for row in rows)}


def full_warmup(model, worker, audio, output):
    import torch
    rounds = []
    speech = audio[:124800]
    for index in range(2):
        # Direct recognition warms shapes that a short natural utterance may never request.
        direct = []
        for count in LENGTHS:
            values = np.resize(speech, count).astype(np.float64)
            began = time.monotonic()
            text = model.cascade_asr.recognize(values, 16000)
            torch.cuda.synchronize()
            direct.append({'samples': count, 'sha256': pcm_digest(values), 'dtype': str(values.dtype), 'text': text,
                           'seconds': time.monotonic() - began, 'source': 'cyclic_fixed_speech'})
        order = ('controller', 'asr') if index == 0 else ('asr', 'controller')
        record = replay(model, worker, audio, f'warmup_{index}', output, False, order)
        record['direct_sensevoice'] = direct
        rounds.append(record)
    required = ['sensevoice_text', 'text_revision', 'native_complete', 'reset']
    if worker is not None:
        required += ['wait', 'multi_token_eos', 'joint_complete', 'joint_wait']
    missing = [{key: record['coverage'].get(key, False) for key in required if not record['coverage'].get(key)}
               for record in rounds]
    passed = all(record['passed'] and not gaps and all(row['text'].strip() for row in record['direct_sensevoice'])
                 and (worker is None or record.get('online_text', '').strip()) for record, gaps in zip(rounds, missing))
    equivalence = compare_native(model, audio)
    write_json(output / 'native_equivalence.json', equivalence)
    first_reset_hash = rounds[0]['cleanup'].get('reset_buffer_sha256')
    reset_rng_equal = bool(first_reset_hash and first_reset_hash == rounds[1]['cleanup'].get('reset_buffer_sha256'))
    return {'rounds': rounds, 'required_paths': required, 'missing_by_round': missing,
            'equivalence': equivalence, 'reset_rng_equal': reset_rng_equal,
            'passed': bool(passed and equivalence['passed'] and reset_rng_equal)}


def compare_native(model, audio):
    """Compare real official and observed calls using the same resident weights."""
    import torch

    def tensor_hash(value):
        return hashlib.sha256(value.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()

    def execute(observed):
        seed_all()
        model.reset()
        trace, records = [], []
        originals = {name: getattr(model, name) for name in ('_audio_to_tokens', '_state_predict', 'reset')}
        recognize, forward = model.cascade_asr.recognize, model.model.llm.forward
        reset_count = [0]

        def reset():
            reset_count[0] += 1
            return originals['reset']()

        def tokens(*args, **kwargs):
            result = originals['_audio_to_tokens'](*args, **kwargs)
            trace.append({'audio_pcm': [pcm_digest(value) for value in args], 'audio_tokens': list(result)})
            return result

        def state(*args, **kwargs):
            result = predict(*args, **kwargs)
            trace.append({'effective_state': result})
            return result

        def asr(*args, **kwargs):
            result = recognize(*args, **kwargs)
            trace.append({'asr_pcm': pcm_digest(args[0]), 'asr_text': result})
            return result

        def llm(*args, **kwargs):
            result = forward(*args, **kwargs)
            trace.append({'llm_input': tensor_hash(kwargs['inputs_embeds']), 'llm_logits': tensor_hash(result.logits)})
            return result

        model.reset, model._audio_to_tokens = reset, tokens
        model.cascade_asr.recognize, model.model.llm.forward = asr, llm
        wrapper = None
        try:
            if observed:
                wrapper = NativeSoulX(model, synchronize=torch.cuda.synchronize)
            predict = model._state_predict
            model._state_predict = state
            ledger = PCMLedger()
            ledger.append(audio)
            ledger.finish()
            submitted = processed = 0
            previous_reset = True
            for step in range((len(audio) + 2559) // 2560):
                before = reset_count[0]
                values, _ = ledger.window(submitted, submitted + 2560)
                if wrapper:
                    receipt = wrapper.step(ledger, step)
                    returned = receipt['native_result']
                else:
                    returned = model.process(values)
                processed = min(len(audio), processed + (1920 if previous_reset else 2560))
                previous_reset = reset_count[0] != before
                submitted = processed if previous_reset else min(submitted + 2560, len(audio))
                records.append({'result': returned, 'resets': reset_count[0],
                    'buffers': {name: pcm_digest(getattr(model, name)) for name in ('buffer', 'buffer_for_asr', 'cascade_buffer')},
                    'control_text': model.past_state['cascade_text'] if model.past_state else None})
            torch.cuda.synchronize()
        finally:
            if wrapper:
                wrapper.detach()
            for name, method in originals.items():
                setattr(model, name, method)
            model.cascade_asr.recognize, model.model.llm.forward = recognize, forward
            seed_all()
            model.reset()
            torch.cuda.synchronize()
        return {'records': records, 'trace': trace}

    reference, observed = execute(False), execute(True)
    return {'passed': reference == observed, 'audio_sha256': pcm_digest(audio),
            'reference': reference, 'observed': observed}


def limited_warmup(model, worker, audio, output):
    import torch
    seed_all()
    model.reset()
    began = time.monotonic()
    for _ in range(3):
        model.process(np.zeros(2560, np.float32))
    text = model.cascade_asr.recognize(np.zeros(53760, np.float32), 16000)
    torch.cuda.synchronize()
    record = {'controller_steps': 3, 'silent_sensevoice_samples': 53760,
              'silent_sensevoice_text': text, 'seconds': time.monotonic() - began, 'x2_rounds': []}
    for index in range(2):
        asr = worker.session(f'limited_warmup_{index}', 'input')
        ledger = PCMLedger()
        cursor = 0
        count = (len(audio) + 1279) // 1280
        with (output / f'x2_warmup_{index}.frames.jsonl').open('x') as stream:
            for frame in range(count):
                target = min(len(audio), (frame + 1) * 1280 + 200)
                ledger.append(audio[cursor:target])
                cursor = target
                if cursor == len(audio) and not ledger.eof:
                    ledger.finish()
                row = asr.step(ledger, frame // 2)
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                ledger.discard_before(max(0, asr.processed_until - 200))
        record['x2_rounds'].append(asr.diagnostics())
        asr.cancel()
        worker.request('clear')
    model.reset()
    record['passed'] = all(row['decoded_text'].strip() for row in record['x2_rounds'])
    return record


def run(args):
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    if digest(args.manifest) != MANIFEST_SHA256:
        raise ValueError('Expected frozen FDB30 manifest')
    manifest = json.loads(args.manifest.read_text())
    if len(manifest['samples']) != 30:
        raise ValueError('Expected fixed denominator 30')
    samples = select_samples(manifest, args.suite, args.condition, args.acceptance_gate, args.acceptance_gate_sha256)
    args.output.mkdir(exist_ok=False)
    result = {'passed': False, 'condition': args.condition, 'cases': [], 'manifest_sha256': digest(args.manifest),
              'fixed_cases': [sample['case_id'] for sample in samples], 'seed': 42, 'warmup_audio_sha256': WARMUP_SHA256,
              'suite': args.suite, 'acceptance_gate_sha256': args.acceptance_gate_sha256,
              'limits': {'latency_stop_ms': None, 'unread_pcm_stop_ms': None, 'pcm_bytes': 4 * 2**20}}
    write_json(args.output / 'input_manifest.json', dict(manifest, samples=samples))
    worker = controller = None
    began = time.monotonic()
    try:
        if args.condition != 'single-full':
            worker = X2Process(args.asr_python, args.assets, args.output)
        controller = load_native_controller(args.upstream, args.assets / 'models/soulx-duplug',
            args.assets / 'models/sensevoice-small', args.output / 'assets')
        model = controller.model
        controller.detach()
        result['load_seconds'] = time.monotonic() - began
        audio, normalization = warmup_audio(args.warmup_audio)
        result['warmup_input'] = {'samples': len(audio), 'sha256': pcm_digest(audio),
                                  'synthetic_tail_samples': 25600, 'sensevoice_lengths': LENGTHS,
                                  'normalization': normalization, 'direct_sensevoice_dtype': 'float64'}
        began = time.monotonic()
        result['warmup'] = (limited_warmup if args.condition == 'dual-limited' else full_warmup)(
            model, worker, audio, args.output)
        result['warmup_seconds'] = time.monotonic() - began
        write_json(args.output / 'warmup.json', result['warmup'])
        if not result['warmup']['passed']:
            raise RuntimeError('Frozen warmup coverage is incomplete; online clock was not started')
        result['ready_at'] = time.monotonic()
        for sample in samples:
            values, gain = load_audio(sample)
            record = replay(model, worker, quantize(values), sample['case_id'], args.output, True, compress=args.suite == 'fdb30')
            record['gain'] = gain
            result['cases'].append(record)
            write_json(args.output / 'progress.json', result)
        result['passed'] = len(result['cases']) == len(samples) and all(record['passed'] for record in result['cases'])
    except Exception:
        result['error'] = traceback.format_exc()
        traceback.print_exc()
    finally:
        if worker:
            worker.close()
        result.update(peak_allocated_mib=torch.cuda.max_memory_allocated() / 2**20,
                      peak_reserved_mib=torch.cuda.max_memory_reserved() / 2**20)
        write_json(args.output / 'result.json', result)
    return 0 if result['passed'] else 1


def select_samples(manifest, suite, condition, gate=None, gate_sha256=None):
    if suite == 'preflight':
        return [next(sample for sample in manifest['samples'] if sample['case_id'] == name) for name in PREFLIGHT]
    if suite != 'fdb30' or condition not in ('dual-full', 'single-full'):
        raise ValueError('Formal FDB30 requires a full warmup condition')
    if gate is None or not gate_sha256 or digest(gate) != gate_sha256:
        raise ValueError('The accepted NTF-018 evidence digest is required')
    accepted = json.loads(Path(gate).read_text())
    dual = accepted.get('conditions', {}).get('dual-full', {})
    if (accepted.get('ntf019_candidate_gate') is not True or accepted.get('resource_checks_passed') is not True
            or dual.get('passed') is not True or [row['case_id'] for row in dual.get('cases', [])] != PREFLIGHT
            or not all(row.get('passed') is True for row in dual['cases'])):
        raise ValueError('NTF-018 did not pass its fixed three-axis gate')
    samples = manifest['samples']
    if len(samples) != 30 or len({row['case_id'] for row in samples}) != 30:
        raise ValueError('Expected thirty distinct frozen cases')
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--condition', required=True, choices=('dual-limited', 'dual-full', 'single-full'))
    parser.add_argument('--suite', choices=('preflight', 'fdb30'), default='preflight')
    parser.add_argument('--acceptance-gate', type=Path)
    parser.add_argument('--acceptance-gate-sha256')
    for name in ('manifest', 'assets', 'upstream', 'warmup-audio', 'asr-python', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
