"""Capture frozen SoulX internals into a typed, revision-aware SharedContext."""
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

    def __init__(self, model, context=None, session_id='session', turn_id='turn',
                 active_output=None, stop_output=None, on_commit=None, audit=None):
        if hasattr(model, '_pt'):
            raise ValueError('Model already has a frontend owner')
        self.model, self.context = model, context if context is not None else SharedContext()
        self.session_id, self.turn_id = session_id, turn_id
        self.active_output, self.stop_output = active_output, stop_output
        if bool(active_output) != bool(stop_output):
            raise ValueError('Output lookup and stop callback must be supplied together')
        self.on_commit, self.audit = on_commit, audit
        self.producer_seq = self.controller_generation = self.call_sequence = self.control_revision = 0
        self.asr_generation = f'{session_id}:{turn_id}:sensevoice'
        self.clock_id = f'{os.uname().nodename}:{os.getpid()}:monotonic'
        self.input_end = self.processed_until = 0
        self.snapshot, self.control = None, None
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
        event = self._event('user_transcript', source='sensevoice_small',
                            version=0, asr_version=0, text='', status='open',
                            assembly_status='empty', coverage_complete=False,
                            audio_spans=[], audio_observed_until=0)
        self._commit([event])
        self.snapshot = event

    def _event(self, kind, source='soulx_frontend', **payload):
        # A single producer namespace orders all event kinds in this session.
        self.producer_seq += 1
        return {'schema_version': 1, 'event_id': f'{self.session_id}:{self.turn_id}:{self.producer_seq}',
                'kind': kind, 'session_id': self.session_id, 'turn_id': self.turn_id,
                'source': source, 'producer_seq': self.producer_seq,
                'producer_id': f'{self.session_id}:{self.turn_id}:frontend',
                'asr_generation': self.asr_generation, 'controller_generation': self.controller_generation,
                'received_at': time.monotonic(), 'clock_id': self.clock_id, **payload}

    def _commit(self, events):
        # Retrying this exact transaction never repeats GPU computation.
        for attempt in range(3):
            try:
                results = self.context.commit_frontend_events(events)
                break
            except (ValueError, RuntimeError):
                raise
            except OSError:
                if attempt == 2:
                    raise
        for event, result in zip(events, results):
            event['committed_seq'] = result['event_seq']
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
        self._commit([self._event('frontend_lifecycle', reason='controller_reset',
                                  processed_until=self.processed_until)])

    def _state_predict(self, chunk, back, ahead):
        self.current_chunk, self.current_ahead = chunk, ahead
        real = [s for s in self._spans(chunk) if s['kind'] == 'real']
        for span in real:
            if span['start'] != self.processed_until:
                raise ValueError('Real audio was skipped, duplicated or reordered across controller resets')
            self.processed_until = span['end']
        self._calls = []
        result = self._instrumented_state(chunk, back, ahead)
        self._check_pcm_bound()
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
        if sample_rate != 16000 or getattr(audio, 'ndim', 1) != 1:
            raise ValueError('Frontend expects mono 16kHz ASR input')
        spans = self._spans(audio)
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
                         model_result=result)
        if error:
            return ''
        native = self.model.cascade_asr
        return native.clean_sensevoice_text(native.rich_transcription_postprocess(raw).strip())

    def observe_asr(self, raw_text, audio_spans, **metadata):
        parsed = SenseVoiceObservation.parse(raw_text)
        call_status = metadata.pop('call_status', 'ok')
        if call_status == 'ok' and not parsed['text']:
            call_status = 'ok_empty'
        observation = self._event('asr_observation', source='sensevoice_small',
                                  **parsed, **metadata, audio_spans=deepcopy(audio_spans),
                                  call_status=call_status, delivery_phase=self.delivery_phase,
                                  source_revision=SENSEVOICE_REVISION)
        real = [s for s in audio_spans if s['kind'] == 'real']
        observation['audio_observed_until'] = max((s['end'] for s in real), default=None)
        checkpoint = self.assembler.checkpoint()
        update = self.assembler.apply_window(observation) if self.delivery_phase == 'online' and not self.closed else {'changed': False, 'reason': 'drain'}
        observation['assembly_result'] = deepcopy(update)
        events = [observation]
        if update['changed']:
            transcript = self._event('user_transcript', source='sensevoice_small',
                                     **{k: v for k, v in update.items() if k not in ('changed', 'text_changed')},
                                     version=self.snapshot['version'] + 1, status='open',
                                     audio_spans=deepcopy(audio_spans),
                                     audio_observed_until=observation['audio_observed_until'],
                                     asr_call_ids=[observation['asr_call_id']],
                                     depends_on=[observation['event_id']], hypothesis=True)
            events.append(transcript)
        if self.audit:
            self.audit('asr_source', deepcopy(observation))
        try:
            self._commit(events)
        except Exception:
            self.assembler.restore(checkpoint)
            raise
        if len(events) > 1:
            self.snapshot = events[-1]
        self._calls.append(observation)
        if len(self._calls) > 4:
            self._calls.pop(0)
        return observation

    def observe_control(self, delta_text, before):
        self.control_revision += 1
        history = self.model.past_state['delta_text']
        corrected = bool(before and history[:-1] != before)
        event = self._event('control_observation', control_revision=self.control_revision,
                            control_text=self.model.past_state['cascade_text'], delta_text=delta_text,
                            delta_token_ids=self.model.model.tokenizer.encode(delta_text, add_special_tokens=False),
                            previous_delta_before=before[-1] if before else '',
                            previous_delta_after=history[-2] if len(history) >= 2 else '',
                            previous_delta_corrected=corrected,
                            asr_call_ids=[v['asr_call_id'] for v in self._calls],
                            depends_on=[v['event_id'] for v in self._calls],
                            asr_status='returned' if self._calls else 'not_requested')
        self._commit([event])
        self.control = event

    def observe_state(self, token, delta_text):
        raw_id, raw_token = self.raw_prediction
        far_field = (token == '<|user_nonidle|>' and not self.model.speech_detected
                     and self.model.get_rms(self.current_chunk) < self.model.config.infer_config.far_field_threshold)
        spans = self._spans(self.current_chunk) + self._spans(self.current_ahead)
        real = [s for s in spans if s['kind'] == 'real']
        reason = ('drain' if self.delivery_phase != 'online' else 'unknown_state' if token not in STATE_IDS
                  else 'far_field' if far_field else 'synthetic_only' if not real else None)
        control = self.control
        basis = {'transcript_version': self.snapshot['version'], 'asr_version': self.snapshot['asr_version'],
                 'control_revision': control['control_revision'], 'control_event_id': control['event_id'],
                 'control_event_seq': control['committed_seq'],
                 'asr_call_ids': control['asr_call_ids'], 'basis_event_seq': self.snapshot['committed_seq'],
                 'audio_observed_until': max((s['end'] for s in real), default=None)}
        output = deepcopy(self.active_output()) if self.active_output and reason is None and token == '<|user_nonidle|>' else None
        event = self._event('user_state', token=token, token_id=STATE_IDS.get(token),
                            raw_token=raw_token, raw_token_id=raw_id,
                            adjustment='native_complete_incomplete_rule' if raw_token != token else None,
                            accepted=reason is None, rejection_reason=reason,
                            basis=basis, audio_spans=spans, processed_spans=self._spans(self.current_chunk),
                            processed_until=self.processed_until, delivery_phase=self.delivery_phase,
                            state_resolved_at=time.monotonic(), source_revision=SOULX_REVISION,
                            depends_on=[self.snapshot['event_id'], control['event_id']],
                            output_id=output.get('output_id') if output else None)
        if self.audit:
            self.audit('state_source', deepcopy(event))
        try:
            self._commit([event])
        finally:
            if output and output.get('output_id') and output['output_id'] not in self._stopped:
                if output.get('session_id', self.session_id) == self.session_id and output.get('phase') in ('preparing', 'playing'):
                    if len(self._stopped) >= 4096:
                        raise RuntimeError('Output cancellation history limit exceeded')
                    self.stop_output(deepcopy(event), output['output_id'])
                    self._stopped.add(output['output_id'])
        return event

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
        if self.closed:
            return
        payload = {k: deepcopy(v) for k, v in self.snapshot.items()
                   if k not in ('schema_version', 'event_id', 'kind', 'source', 'session_id', 'turn_id',
                                'producer_seq', 'producer_id', 'asr_generation', 'controller_generation',
                                'received_at', 'clock_id', 'committed_seq')}
        payload.update(version=self.snapshot['version'] + 1, status='closed', close_reason=reason,
                       depends_on=[self.snapshot['event_id']])
        event = self._event('user_transcript', source='sensevoice_small', **payload)
        self._commit([event])
        self.snapshot, self.closed, self.delivery_phase = event, True, 'drain'

    def detach(self, *, aborted=False):
        if not self.closed and not aborted:
            raise ValueError('Close the logical turn before detaching capture hooks')
        if aborted:
            self.closed, self.delivery_phase = True, 'drain'
        for name, method in self._original.items():
            setattr(self.model, name, method)
        self.model.cascade_asr.recognize = self._original_recognize
        del self.model._pt
