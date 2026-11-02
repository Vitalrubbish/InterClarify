"""Observe the frozen native SoulX protocol without replacing its teacher."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
import threading
import time
import types
import weakref

import numpy as np


SOURCE_SHA256 = '85d9d049c47d42fda2797806024044d141e2703fd6a63ef2853cbd29887f2a52'
STATES = {f'<|user_{name}|>' for name in ('idle', 'nonidle', 'backchannel', 'incomplete', 'complete')}


def pcm_digest(audio):
    return hashlib.sha256(np.asarray(audio, dtype='<f4').tobytes()).hexdigest()


def slice_spans(spans, begin, end):
    result, position = [], 0
    for span in spans:
        left, right = max(begin, position), min(end, position + span['samples'])
        if left < right:
            item = dict(span, samples=right - left)
            if span['kind'] == 'real':
                item.update(start=span['start'] + left - position, end=span['start'] + right - position)
            result.append(item)
        position += span['samples']
    if sum(s['samples'] for s in result) != end - begin:
        raise ValueError('PCM provenance does not cover the requested slice')
    return result


def real_end(spans, default=0):
    return max((s['end'] for s in spans if s['kind'] == 'real'), default=default)


class _Capture(ast.NodeTransformer):
    """Add read-only observations and track existing PCM concatenations."""

    def __init__(self):
        self.counts = [0, 0, 0, 0]

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if (node.func.value.id, node.func.attr) == ('np', 'concatenate'):
                self.counts[0] += 1
                node.func = ast.parse('self._native.concatenate', mode='eval').body
        return node

    def visit_Subscript(self, node):
        self.generic_visit(node)
        if (isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name)
                and node.value.value.id == 'self' and node.value.attr == 'cascade_buffer'):
            self.counts[1] += 1
            return ast.copy_location(ast.Call(
                func=ast.parse('self._native.slice_audio', mode='eval').body,
                args=[node.value, ast.Call(func=ast.Name(id='slice', ctx=ast.Load()),
                      args=[node.slice.lower or ast.Constant(None), node.slice.upper or ast.Constant(None)],
                      keywords=[])], keywords=[]), node)
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'state' and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'decode'):
            self.counts[2] += 1
            return [node] + ast.parse('self._native.raw_prediction = (int(pred.item()), state)').body
        return node

    def visit_Return(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == 'state':
            self.counts[3] += 1
            return ast.parse('self._native.capture_state(state, delta_text)\nreturn state').body
        return node


def capture_methods(model, source_path=None):
    path = Path(source_path or inspect.getfile(type(model)))
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Native SoulX source digest differs')
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'TurnModel')
    names = {'infer', '_asr', '_state_predict', 'state_predict'}
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    capture = _Capture()
    tree = capture.visit(ast.Module(body=methods, type_ignores=[]))
    if {n.name for n in methods} != names or capture.counts != [5, 1, 1, 1]:
        raise ValueError('Native SoulX observation sites differ')
    ast.fix_missing_locations(tree)
    namespace = dict(inspect.unwrap(model.infer.__func__).__globals__)
    exec(compile(tree, str(path) + ':native-capture', 'exec'), namespace)
    return {name: types.MethodType(namespace[name], model) for name in names}


class NativeSoulX:
    """Own one native controller; external PCM survives internal reset."""

    def __init__(self, model, *, synchronize, source_path=None, on_state=None,
                 session_id='session', turn_id='turn',
                 is_live=lambda: True, clock=time.monotonic):
        cfg = model.config.infer_config
        inp = cfg.input
        if (inp.sample_rate, inp.chunk_size, inp.audio_back_size, inp.audio_ahead_size) != (16000, 2560, 15360, 640):
            raise ValueError('Native SoulX PCM contract differs')
        if cfg.asr.model_name != 'sensevoice' or cfg.asr.language != 'en':
            raise ValueError('Native English SenseVoice is required')
        if hasattr(model, '_native') or hasattr(model, '_pt'):
            raise ValueError('Controller already has an owner')
        methods = capture_methods(model, source_path)
        self.model, self.synchronize, self.clock = model, synchronize, clock
        self.on_state, self.is_live = on_state, is_live
        self.session_id, self.turn_id = session_id, turn_id
        self.generation = self.processed_until = self.submitted_until = 0
        self.closed, self._arrays = False, {}
        self._feeding = threading.Lock()
        self._publishing = threading.RLock()
        self._original = {name: getattr(model, name) for name in (*methods, 'reset', 'get_chunk')}
        self._recognize = model.cascade_asr.recognize
        self._events, self._frame, self._windows = [], None, None
        self.failure = None
        self.reserve_pcm = lambda size: None
        self._reset_spans()
        model._native = self
        for name, method in methods.items():
            setattr(model, name, method)
        model.reset, model.get_chunk = self._reset, self._get_chunk
        model.cascade_asr.recognize = self._observe_recognize

    def _record(self, audio, spans):
        key = id(audio)
        self._arrays[key] = (weakref.ref(audio, lambda _: self._arrays.pop(key, None)), spans)
        return audio

    def _spans(self, audio):
        record = self._arrays.get(id(audio))
        if record is None or record[0]() is not audio:
            raise ValueError('Untracked native PCM')
        return record[1]

    def _reset_spans(self):
        for name in ('buffer', 'buffer_for_asr', 'cascade_buffer'):
            value = getattr(self.model, name)
            self._record(value, [{'kind': 'synthetic', 'reason': 'native_reset',
                                 'generation': self.generation, 'samples': len(value)}])

    def concatenate(self, arrays, axis=0):
        size = sum(len(a) for a in arrays) * np.result_type(*(a.dtype for a in arrays)).itemsize
        self.reserve_pcm(size)
        result = np.concatenate(arrays, axis=axis)
        return self._record(result, [s for a in arrays for s in self._spans(a)])

    def slice_audio(self, audio, selection):
        begin, end, stride = selection.indices(len(audio))
        if stride != 1:
            raise ValueError('Unsupported native PCM stride')
        return self._record(audio[selection], slice_spans(self._spans(audio), begin, end))

    def _get_chunk(self):
        spans = self._pending_buffer_spans
        self._record(self.model.buffer, spans)
        self.reserve_pcm((15360 + 2560 + 640) * 4)
        result = self._original['get_chunk']()
        if result[0]:
            self._windows = {}
            for name, audio, start, end in (('main', result[1], 15360, 17920),
                                           ('lookback', result[2], 0, 15360),
                                           ('lookahead', result[3], 17920, 18560)):
                items = slice_spans(spans, start, end)
                self._record(audio, items)
                self._windows[name] = {'spans': deepcopy(items), 'sha256': pcm_digest(audio)}
            self._record(self.model.buffer, slice_spans(spans, 2560, sum(s['samples'] for s in spans)))
            self.processed_until = real_end(self._windows['main']['spans'], self.processed_until)
            self._chunk = result[1]
        return result

    def _reset(self):
        before = self.generation
        unread = self._spans(self.model.buffer)
        self.reserve_pcm((16000 + 25600 + 51200) * 8)
        self._original['reset']()
        self.generation += 1
        self.submitted_until = self.processed_until
        self._reset_spans()
        self._events.append({'kind': 'reset', 'before': before, 'after': self.generation,
                             'resume_from': self.processed_until, 'discarded_internal_spans': deepcopy(unread)})

    def _observe_recognize(self, audio, *args, **kwargs):
        call = {'kind': 'sensevoice', 'spans': deepcopy(self._spans(audio)),
                'sha256': pcm_digest(audio), 'dtype': str(audio.dtype), 'started_at': self.clock()}
        result = self._recognize(audio, *args, **kwargs)
        call.update(control_text=result, completed_at=self.clock())
        self._events.append(call)
        return result

    def capture_state(self, token, delta_text):
        self.synchronize()
        speech = bool(self.model.speech_detected)
        rejected = ('unknown_state' if token not in STATES else
                    'far_field' if token == '<|user_nonidle|>' and not speech and
                    self.model.get_rms(self._chunk) < self.model.config.infer_config.far_field_threshold else
                    'no_speech' if token == '<|user_complete|>' and not speech else None)
        frame = {'session_id': self.session_id, 'turn_id': self.turn_id,
                 'step_id': self._step_id, 'controller_generation': self.generation,
                 'raw_token_id': self.raw_prediction[0], 'raw_token': self.raw_prediction[1],
                 'state_token': token, 'rule_applied': self.raw_prediction[1] != token,
                 'state_accepted': rejected is None, 'rejection_reason': rejected,
                 'speech_detected_before_service': speech, 'control_delta': delta_text,
                 'control_text': self.model.past_state['cascade_text'],
                 'state_processed_until': self.processed_until,
                 'state_observed_until': real_end(self._windows['lookahead']['spans'], self.processed_until),
                 'state_available_at': self.clock()}
        self._frame = frame
        with self._publishing:
            if not self.closed and self.is_live() and self.on_state:
                self.on_state(deepcopy(frame))
        self._events.append(dict(frame, kind='state'))

    def step(self, ledger, step_id):
        if not self._feeding.acquire(blocking=False):
            raise RuntimeError('Native controller calls must be serial')
        try:
            if self.closed or not self.is_live():
                raise RuntimeError('Native controller is closed')
            started_at = self.clock()
            self._events, self._frame, self._step_id = [], None, step_id
            self.raw_prediction = (None, None)
            start = self.submitted_until
            audio, spans = ledger.window(start, start + 2560)
            self.submitted_until = real_end(spans, start)
            self._record(audio, spans)
            self._pending_buffer_spans = self._spans(self.model.buffer) + spans
            result = self.model.process(audio)
            self.synchronize()
            if self._frame is None:
                raise RuntimeError('Native call produced no state observation')
            service_state = result['state']
            source = None
            if service_state == 'speak':
                source = ('model_complete' if self._frame['state_token'] == '<|user_complete|>'
                          and self._frame['state_accepted'] else 'wait_fallback')
            if self.closed or not self.is_live():
                raise RuntimeError('Native call completed after cancellation')
            return {'lane': 'controller', 'session_id': self.session_id, 'turn_id': self.turn_id,
                    'step_id': step_id, 'started_at': started_at, 'completed_at': self.clock(),
                    'processed_until': self.processed_until, 'submitted_until': self.submitted_until,
                    'windows': self._windows, 'state': deepcopy(self._frame),
                    'service_state': service_state, 'service_completion_source': source,
                    'service_text': result.get('text') or '', 'native_result': result,
                    'generation_after': self.generation, 'events': deepcopy(self._events)}
        except Exception as exc:
            self.closed, self.failure = True, str(exc)
            raise
        finally:
            self._chunk = None
            self._feeding.release()

    def cancel(self):
        with self._publishing:
            self.closed = True

    def pcm_bytes(self):
        # Count owning allocations once, including history chunks and live views.
        roots = {}
        for reference, _ in list(self._arrays.values()):
            array = reference()
            if array is None:
                continue
            while isinstance(array.base, np.ndarray):
                array = array.base
            roots[id(array)] = array.nbytes
        return sum(roots.values())

    def detach(self):
        if self._feeding.locked():
            raise RuntimeError('Cannot detach an executing controller')
        self.closed = True
        for name, method in self._original.items():
            setattr(self.model, name, method)
        self.model.cascade_asr.recognize = self._recognize
        del self.model._native
        self._arrays.clear()
