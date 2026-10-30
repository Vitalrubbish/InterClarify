"""Publish each frozen SoulX audio step as one current text/state observation."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
import os
from pathlib import Path
import threading
import time
import types
import weakref

try:
    from .shared_context import SharedContext, STATE_IDS
    from .sensevoice_transcript import SenseVoiceObservation, TurnTranscriptAssembler, KNOWN_TAGS
except ImportError:
    from shared_context import SharedContext, STATE_IDS
    from sensevoice_transcript import SenseVoiceObservation, TurnTranscriptAssembler, KNOWN_TAGS


UPSTREAM_SHA256 = '85d9d049c47d42fda2797806024044d141e2703fd6a63ef2853cbd29887f2a52'
SOULX_REVISION = '61701c4ab8193cc1ee2220d3848872ac6c720142'
SENSEVOICE_REVISION = '3847d57b6bdf2dd8875cb1508d2af43d80a16bf7'


def slice_spans(spans, begin, end):
    """Slice a concatenated sample ledger without inventing continuous coverage."""
    result, position = [], 0
    for span in spans:
        length = span['samples']
        left, right = max(begin, position), min(end, position + length)
        if left < right:
            value = dict(span, samples=right - left)
            if span['kind'] == 'real':
                value.update(start=span['start'] + left - position,
                             end=span['start'] + right - position)
            result.append(value)
        position += length
    if sum(s['samples'] for s in result) != end - begin:
        raise ValueError('Audio ledger slice exceeds recorded samples')
    return result


class _Instrumentation(ast.NodeTransformer):
    """Insert callbacks into four hash-verified methods without editing assets."""

    def __init__(self):
        self.concatenations = self.slices = self.raw_hooks = self.state_hooks = 0

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'np' and node.func.attr == 'concatenate':
            self.concatenations += 1
            node.func = ast.parse('self._pt.concat_audio', mode='eval').body
        return node

    def visit_Subscript(self, node):
        self.generic_visit(node)
        if (isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name)
                and node.value.value.id == 'self' and node.value.attr == 'cascade_buffer'):
            self.slices += 1
            return ast.copy_location(ast.Call(func=ast.parse('self._pt.slice_audio', mode='eval').body,
                                             args=[node.value, ast.Call(func=ast.Name(id='slice', ctx=ast.Load()),
                                                   args=[node.slice.lower or ast.Constant(None),
                                                         node.slice.upper or ast.Constant(None)], keywords=[])], keywords=[]), node)
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'state' and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'decode'):
            self.raw_hooks += 1
            return [node] + ast.parse('self._pt.raw_prediction = (int(pred.item()), state)').body
        return node

    def visit_Return(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == 'state':
            self.state_hooks += 1
            return ast.parse('self._pt.observe_state(state, delta_text)\nreturn state').body
        return node


def instrument_methods(model):
    source_path = Path(inspect.getfile(type(model)))
    source = source_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('SoulX source digest differs from the audited version')
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TurnModel')
    names = {'infer', '_asr', '_state_predict', 'state_predict'}
    functions = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in functions} != names:
        raise ValueError('Frozen SoulX instrumentation methods are missing')
    transformer = _Instrumentation()
    module = transformer.visit(ast.Module(body=functions, type_ignores=[]))
    ast.fix_missing_locations(module)
    counts = (transformer.concatenations, transformer.slices, transformer.raw_hooks, transformer.state_hooks)
    if counts != (5, 1, 1, 1):
        raise ValueError(f'SoulX instrumentation sites differ: {counts}')
    namespace = dict(vars(inspect.getmodule(type(model))))
    exec(compile(module, str(source_path) + ':parathink-instrumented', 'exec'), namespace)
    return {name: types.MethodType(namespace[name], model) for name in names}


class SoulXFrontend:
    """Own capture hooks, audio provenance and one stable logical user turn."""

    transcript_source = 'sensevoice_small'

    def __init__(self, model, context=None, session_id='session', turn_id='turn',
                 active_output=None, stop_output=None, on_commit=None, audit=None):
        if hasattr(model, '_pt'):
            raise ValueError('Model already has a frontend owner')
        audio_config = model.config.infer_config.input
        if (audio_config.sample_rate, audio_config.chunk_size) != (16000, 2560):
            raise ValueError('SoulX frontend requires 160ms blocks at 16kHz')
        self.model, self.context = model, context if context is not None else SharedContext()
        self.session_id, self.turn_id = session_id, turn_id
        self.active_output, self.stop_output = active_output, stop_output
        if bool(active_output) != bool(stop_output):
            raise ValueError('Output lookup and stop callback must be supplied together')
        self.on_commit, self.audit = on_commit, audit
        self.controller_generation = self.call_sequence = 0
        self.asr_generation = f'{session_id}:{turn_id}:{self.transcript_source}'
        self.clock_id = f'{os.uname().nodename}:{os.getpid()}:monotonic'
        self.input_end = self.processed_until = 0
        self.snapshot, self.control, self._pending_state = None, None, None
        self.assembler = TurnTranscriptAssembler()
        self._arrays, self._calls = {}, []
        self._feeding = threading.Lock()
        self._in_asr, self.closed = False, False
        self._stopped = set()
        self.delivery_phase = 'online'
        self.raw_prediction = (None, None)
        tokenizer = model.model.tokenizer
        for token, expected in STATE_IDS.items():
            ids = tokenizer.encode(token, add_special_tokens=False)
            config_name = token[2:-2] + '_token_id'
            if ids != [expected] or tokenizer.decode(ids, skip_special_tokens=False) != token or getattr(model.config.model_config, config_name) != expected:
                raise ValueError(f'Invalid SoulX token mapping: {token}')
        self.postprocess_sha256 = None
        if self.transcript_source == 'sensevoice_small':
            from funasr.utils import postprocess_utils
            if frozenset(postprocess_utils.emoji_dict) != KNOWN_TAGS | {'<|nospeech|><|Event_UNK|>'}:
                raise ValueError('Installed SenseVoice postprocessing label table differs')
            self.postprocess_sha256 = hashlib.sha256(Path(postprocess_utils.__file__).read_bytes()).hexdigest()
            if self.postprocess_sha256 != '199fb27009931c33e1b80bca8436a249b6ced43897854a3f910222be5c525d85':
                raise ValueError('Installed FunASR 1.2.6 postprocessing digest differs')
        patched = instrument_methods(model)
        self._original = {name: getattr(model, name) for name in
                          ('reset', 'get_chunk', 'infer', '_asr', '_state_predict', 'state_predict')}
        self._original_recognize = model.cascade_asr.recognize
        for name, method in patched.items():
            setattr(model, name, method)
        self._instrumented_asr, self._instrumented_state = model._asr, model.state_predict
        model._pt = self
        model.reset = self._reset_controller
        model.get_chunk = self._get_chunk
        model._asr = self._asr
        model.state_predict = self._state_predict
        model.cascade_asr.recognize = self._recognize
        self._register_reset_buffers()
        self.snapshot = self.context.open_user_turn(session_id, turn_id)
        if self.on_commit:
            self.on_commit(self.context)

    def _audit(self, kind, observation):
        # Diagnostics are external to SharedContext and never form text history.
        if self.audit:
            self.audit(kind, deepcopy(observation))

    def _publish(self, frame):
        self.snapshot = self.context.publish_user_frame(frame)
        if self.on_commit:
            self.on_commit(self.context)

    def _record_array(self, array, spans):
        if len(array) != sum(s['samples'] for s in spans):
            raise ValueError('Audio array length differs from its ledger')
        key = id(array)
        def expire(reference):
            if self._arrays.get(key, (None,))[0] is reference:
                self._arrays.pop(key, None)
        self._arrays[key] = (weakref.ref(array, expire), deepcopy(spans))
        return array

    def _spans(self, array):
        record = self._arrays.get(id(array))
        if record is None or record[0]() is not array:
            raise ValueError('Untracked audio supplied to SoulX')
        return deepcopy(record[1])

    def _register_reset_buffers(self):
        for name in ('buffer', 'buffer_for_asr', 'cascade_buffer'):
            array = getattr(self.model, name)
            self._record_array(array, [{'kind': 'synthetic', 'samples': len(array), 'reason': 'controller_initial_padding'}])

    def concat_audio(self, arrays, axis=0):
        import numpy as np
        values = list(arrays)
        return self._record_array(np.concatenate(values, axis=axis),
                                  [span for array in values for span in self._spans(array)])

    def slice_audio(self, array, selection):
        begin, end, step = selection.indices(len(array))
        if step != 1:
            raise ValueError('Non-contiguous audio ledger slice')
        return self._record_array(array[selection], slice_spans(self._spans(array), begin, end))

    def _get_chunk(self):
        model = self.model
        spans = self._spans(model.buffer)
        length = len(model.buffer)
        ready, chunk, back, ahead = self._original['get_chunk']()
        if ready:
            cfg = model.config.infer_config.input
            for array, begin, end in ((back, 0, cfg.audio_back_size),
                                      (chunk, cfg.audio_back_size, cfg.audio_back_size + cfg.chunk_size),
                                      (ahead, cfg.audio_back_size + cfg.chunk_size,
                                       cfg.audio_back_size + cfg.chunk_size + cfg.audio_ahead_size)):
                self._record_array(array, slice_spans(spans, begin, end))
            self._record_array(model.buffer, slice_spans(spans, cfg.chunk_size, length))
        return ready, chunk, back, ahead

    def _reset_controller(self):
        carry, spans = self.model.buffer, self._spans(self.model.buffer)
        self._original['reset']()
        self._register_reset_buffers()
        self.model.buffer = self._record_array(carry, spans)
        self.controller_generation += 1
        self.control = None
        self._audit('controller_reset', {'controller_generation': self.controller_generation,
                                         'processed_until': self.processed_until})

    def _state_predict(self, chunk, back, ahead):
        self.current_chunk, self.current_ahead = chunk, ahead
        real = [s for s in self._spans(chunk) if s['kind'] == 'real']
        for span in real:
            if span['start'] != self.processed_until:
                raise ValueError('Real audio was skipped, duplicated or reordered across controller resets')
            self.processed_until = span['end']
        self._calls = []
        self._pending_state = None
        result = self._instrumented_state(chunk, back, ahead)
        if self._pending_state is None:
            raise RuntimeError('SoulX did not produce a state for the audio step')
        frame = {**self._pending_state, 'text': self.assembler.text,
                 'assembly_status': self.assembler.assembly_status,
                 'coverage_complete': self.assembler.coverage_complete}
        self._pending_state = None
        self._check_pcm_bound()
        if self.delivery_phase == 'online' and not self.closed and real:
            self._audit('frame_source', frame)
            self._publish(frame)
        return result

    def _asr(self, audio_embeds):
        before = list(self.model.past_state.get('delta_text', []))
        self._in_asr = True
        try:
            delta = self._instrumented_asr(audio_embeds)
        finally:
            self._in_asr = False
        self.observe_control(delta, before)
        return delta

    def _recognize(self, audio, sample_rate=16000, language=None):
        import numpy as np
        if sample_rate != 16000 or getattr(audio, 'ndim', 1) != 1:
            raise ValueError('Frontend expects mono 16kHz ASR input')
        spans = self._spans(audio)
        audio = np.asarray(audio, dtype=np.float32)
        self.call_sequence += 1
        call_id = f'{self.asr_generation}:call:{self.call_sequence}'
        started = time.monotonic()
        error, raw, result = None, '', None
        try:
            result = self.model.cascade_asr.sensevoice_model.generate(
                input=audio, cache={}, language=language or self.model.cascade_asr.language,
                use_itn=True, batch_size=16)
            raw = result[0]['text']
            if not isinstance(raw, str):
                raise ValueError('SenseVoice returned a non-string text')
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
        returned = time.monotonic()
        self.observe_asr(raw, spans, asr_call_id=call_id,
                         call_kind='window' if self._in_asr else 'turn',
                         call_status='error' if error else 'ok', error=error,
                         asr_started_at=started, asr_returned_at=returned,
                         model_result=result, asr_input_dtype=str(audio.dtype))
        if error:
            return ''
        native = self.model.cascade_asr
        return native.clean_sensevoice_text(native.rich_transcription_postprocess(raw).strip())

    def observe_asr(self, raw_text, audio_spans, **metadata):
        parsed = SenseVoiceObservation.parse(raw_text)
        call_status = metadata.pop('call_status', 'ok')
        if call_status == 'ok' and not parsed['text']:
            call_status = 'ok_empty'
        observation = dict(parsed, **metadata, audio_spans=deepcopy(audio_spans),
                           call_status=call_status, delivery_phase=self.delivery_phase,
                           source_revision=SENSEVOICE_REVISION)
        real = [span for span in audio_spans if span['kind'] == 'real']
        observation['audio_observed_until'] = max((span['end'] for span in real), default=None)
        update = self.assembler.apply_window(observation) if self.delivery_phase == 'online' and not self.closed else {'changed': False, 'reason': 'drain'}
        observation['assembly_result'] = update
        self._audit('asr_source', observation)
        self._calls.append({'asr_call_id': observation['asr_call_id'],
                            'call_status': call_status,
                            'audio_observed_until': observation['audio_observed_until']})
        self._calls = self._calls[-4:]
        return observation

    def observe_control(self, delta_text, before):
        history = self.model.past_state['delta_text']
        self.control = {'control_text': self.model.past_state['cascade_text'],
                        'delta_text': delta_text,
                        'previous_delta_corrected': bool(before and history[:-1] != before),
                        'asr_calls': deepcopy(self._calls)}
        self._audit('control_source', self.control)

    def observe_state(self, token, delta_text):
        raw_id, raw_token = self.raw_prediction
        far_field = (token == '<|user_nonidle|>' and not self.model.speech_detected
                     and self.model.get_rms(self.current_chunk) < self.model.config.infer_config.far_field_threshold)
        spans = self._spans(self.current_chunk) + self._spans(self.current_ahead)
        real = [span for span in spans if span['kind'] == 'real']
        reason = ('drain' if self.delivery_phase != 'online' or self.closed
                  else 'unknown_state' if token not in STATE_IDS
                  else 'far_field' if far_field else 'synthetic_only' if not real else None)
        frame = {'session_id': self.session_id, 'turn_id': self.turn_id,
                 'source': self.transcript_source, 'status': 'open',
                 'state_token': token, 'state_token_id': STATE_IDS.get(token),
                 'state_accepted': reason is None, 'rejection_reason': reason,
                 'raw_token': raw_token, 'raw_token_id': raw_id,
                 'adjustment': 'native_complete_incomplete_rule' if raw_token != token else None,
                 'controller_generation': self.controller_generation,
                 'processed_until': self.processed_until,
                 'audio_observed_until': max((span['end'] for span in real), default=self.processed_until),
                 'state_resolved_at': time.monotonic(), 'clock_id': self.clock_id,
                 'delivery_phase': self.delivery_phase}
        self._pending_state = frame
        # The native completion branch may run whole-turn ASR and reset after
        # this hook; publish text and state together only after that branch.
        try:
            if reason is None and token == '<|user_nonidle|>' and self.active_output:
                output = deepcopy(self.active_output())
                if (output and output.get('output_id') and output['output_id'] not in self._stopped
                        and output.get('session_id', self.session_id) == self.session_id
                        and output.get('phase') in ('preparing', 'playing')):
                    if len(self._stopped) >= 4096:
                        raise RuntimeError('Output cancellation history limit exceeded')
                    self.stop_output(deepcopy(frame), output['output_id'])
                    self._stopped.add(output['output_id'])
        finally:
            self._audit('state_source', frame)
        return frame

    def _check_pcm_bound(self):
        arrays = [record[0]() for record in self._arrays.values()]
        size = sum(array.nbytes for array in arrays if array is not None)
        if size > 4 * 1024 * 1024:
            raise RuntimeError('Frontend PCM byte limit exceeded')

    def feed_audio(self, audio, *, synthetic=False, reason='explicit_silence_tail'):
        import numpy as np
        if self.closed:
            raise ValueError('Cannot feed a closed user turn')
        if not self._feeding.acquire(blocking=False):
            raise RuntimeError('Concurrent calls into a stateful SoulX model are forbidden')
        try:
            if self.closed:
                raise ValueError('Cannot feed a closed user turn')
            if not isinstance(audio, np.ndarray) or audio.dtype != np.float32 or audio.ndim != 1 or not np.isfinite(audio).all():
                raise ValueError('Expected finite mono float32 16kHz samples')
            if not 0 < len(audio) <= 12800:
                raise ValueError('Input packet exceeds the 800ms audio bound')
            spans = [{'kind': 'synthetic', 'samples': len(audio), 'reason': reason}] if synthetic else [
                {'kind': 'real', 'samples': len(audio), 'start': self.input_end, 'end': self.input_end + len(audio)}]
            self.input_end += 0 if synthetic else len(audio)
            self._record_array(audio, spans)
            previous = self._spans(self.model.buffer)
            # Official process concatenates once before calling get_chunk.
            original_get = self.model.get_chunk
            def capture_get():
                self._record_array(self.model.buffer, previous + spans)
                return original_get()
            self.model.get_chunk = capture_get
            try:
                results = [self.model.process(audio)]
            finally:
                self.model.get_chunk = original_get
            cfg = self.model.config.infer_config.input
            while len(self.model.buffer) >= cfg.audio_back_size + cfg.chunk_size + cfg.audio_ahead_size:
                ready, chunk, back, ahead = self._get_chunk()
                if not ready:
                    break
                results.append(self._state_predict(chunk, back, ahead))
            self._check_pcm_bound()
            return results
        finally:
            self._feeding.release()

    def close_turn(self, reason='runtime_audio_case_end'):
        if not self._feeding.acquire(blocking=False):
            raise RuntimeError('Cannot close a turn during model computation')
        try:
            if self.closed:
                return
            self.snapshot = self.context.close_user_turn(self.session_id, self.turn_id, reason)
            self.closed, self.delivery_phase = True, 'drain'
            if self.on_commit:
                self.on_commit(self.context)
        finally:
            self._feeding.release()

    def detach(self, *, aborted=False):
        if not self.closed and not aborted:
            raise ValueError('Close the logical turn before detaching capture hooks')
        if aborted:
            self.closed, self.delivery_phase = True, 'drain'
        for name, method in self._original.items():
            setattr(self.model, name, method)
        self.model.cascade_asr.recognize = self._original_recognize
        del self.model._pt
