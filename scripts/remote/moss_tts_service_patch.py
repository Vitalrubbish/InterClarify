"""Explicit, opt-in instrumentation and bounded generation for pinned MOSS."""
from __future__ import annotations

import functools
import hashlib
import importlib.util
import os
import queue
import sys
import threading
import uuid
from pathlib import Path

from tts_latency_trace import emit, span, trace_scope


def generation_batch_frames() -> int:
    """Validate the independent batch-size experiment."""
    value = int(os.environ.get('XTALK_TTS_GENERATION_BATCH_FRAMES', '0'))
    if value not in (0, 2, 4, 6):
        raise ValueError('XTALK_TTS_GENERATION_BATCH_FRAMES must be 0, 2, 4 or 6')
    return value


def bounded_pending(session, limit: int, cancelled):
    """Generate batches lazily, preserving upstream token and state order."""
    while not cancelled():
        with span('generation_batch', limit=limit):
            batch = list(session._prefill_if_needed())
            if not session._prefilled:
                return
            while (len(batch) < limit and session._pending_tokens
                   and not session.inferencer.is_finished and not cancelled()):
                token = session._pending_tokens.pop(0)
                batch.append(session.inferencer.step(
                    token, temperature=session.temperature, top_p=session.top_p,
                    top_k=session.top_k, do_sample=session.do_sample,
                    repetition_penalty=session.repetition_penalty,
                    repetition_window=session.repetition_window))
        emit('generation_batch.ready', frames=len(batch))
        if cancelled():
            return
        for frame in batch:
            if cancelled():
                return
            yield frame
        if (not session._pending_tokens or session.inferencer.is_finished
                or not batch):
            return


class ObservedQueue(queue.Queue):
    """Keep queue semantics while recording enqueue and dequeue times."""

    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def put(self, item, *args, **kwargs):
        """Record command availability before publishing it to the worker."""
        item = {**item, '_xt_command_id': str(uuid.uuid4())}
        with trace_scope(self.session_id, self.session_id):
            emit('queue.put', command=item.get('type'), command_id=item['_xt_command_id'])
        return super().put(item, *args, **kwargs)

    def get(self, *args, **kwargs):
        """Record when the original worker takes ownership."""
        item = super().get(*args, **kwargs)
        with trace_scope(self.session_id, self.session_id):
            emit('queue.get', command=item.get('type'), command_id=item['_xt_command_id'])
        return item


def apply_service_patch(module):
    """Wrap the pinned service without touching its source checkout."""
    limit = generation_batch_frames()
    manager = module.SessionManager
    original_start = manager._start_worker

    def start_worker(self, sess):
        sess.command_queue = ObservedQueue(sess.session_id)
        sess._xt_cancelled = threading.Event()
        sess._xt_commit_lock = threading.Lock()
        return original_start(self, sess)

    manager._start_worker = start_worker
    original_worker = manager._session_worker

    def worker(self, sess):
        try:
            with trace_scope(sess.session_id, sess.session_id):
                return original_worker(self, sess)
        finally:
            context = sess.codec_stream_cm
            if context is not None:
                sess.codec_stream_cm = None
                context.__exit__(None, None, None)

    manager._session_worker = worker
    original_delete = manager.delete

    def delete(self, session_id):
        sess = self.get(session_id)
        if sess is not None:
            with sess._xt_commit_lock:
                sess._xt_cancelled.set()
            with trace_scope(session_id, session_id):
                emit('cancel')
        return original_delete(self, session_id)

    manager.delete = delete
    if os.environ.get('XTALK_TTS_SEED'):
        from dataclasses import replace
        seed = int(os.environ['XTALK_TTS_SEED'])
        original_generation = manager._make_generation

        def generation(self):
            return replace(original_generation(self), seed=seed)

        manager._make_generation = generation
    original_session = module.MossTTSRealtimeStreamingSession

    class InstrumentedSession(original_session):
        """Only this service uses the optional lazy pending-token path."""

        def _drain_pending_tokens(self):
            emit('text_gate', pending_tokens=len(self._pending_tokens),
                 prefill_text_len=self.prefill_text_len,
                 text_ended=self._text_ended, prefilled=self._prefilled)
            if not self._prefilled and (self._text_ended or len(self._pending_tokens) >= self.prefill_text_len):
                emit('text_gate.ready', prefill_text_len=self.prefill_text_len)
            if not limit:
                with span('generation_batch', limit=0):
                    frames = super()._drain_pending_tokens()
                emit('generation_batch.ready', frames=len(frames))
                return frames
            return bounded_pending(self, limit, self._xt_cancelled)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._xt_cancelled = lambda: False

    module.MossTTSRealtimeStreamingSession = InstrumentedSession
    for name in ('_handle_start_turn', '_handle_push_text', '_handle_finish_turn'):
        original = getattr(manager, name)

        def wrap_handler(original, name):
            @functools.wraps(original)
            def handler(self, sess, *args, **kwargs):
                if sess._xt_cancelled.is_set():
                    return
                with trace_scope(sess.session_id, sess.session_id), span(name):
                    result = original(self, sess, *args, **kwargs)
                    return result
            return handler

        setattr(manager, name, wrap_handler(original, name))

    # Bind cancellation before start_turn pushes its optional initial text.
    original_init = InstrumentedSession.__init__
    current_session = threading.local()

    def session_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._xt_cancelled = current_session.cancelled

    InstrumentedSession.__init__ = session_init
    traced_start = manager._handle_start_turn

    def handle_start(self, sess, cmd):
        current_session.cancelled = sess._xt_cancelled.is_set
        try:
            return traced_start(self, sess, cmd)
        finally:
            del current_session.cancelled

    manager._handle_start_turn = handle_start
    def emit_chunks(self, sess, chunks):
        for chunk in chunks:
            if sess._xt_cancelled.is_set():
                return
            if chunk.size == 0:
                continue
            emit('pcm.ready', samples=int(chunk.size), sample_rate=module.SAMPLE_RATE)
            module._maybe_wait_for_buffer(sess.buffer_tracker, sess.streaming.buffer_threshold_seconds)
            with sess._xt_commit_lock:
                if sess._xt_cancelled.is_set():
                    return
                sess.buffer_tracker.add_chunk(chunk)
                x = module.np.asarray(chunk, dtype=module.np.float32).reshape(-1)
                x = module.resample_if_needed(x, module.SAMPLE_RATE, module.TARGET_SR)
                pcm = module.float32_to_pcm16_bytes(x)
                sess.audio_queue.put(pcm)
                emit('pcm.enqueued', samples=len(pcm) // 2, sample_rate=module.TARGET_SR)

    manager._emit_audio_chunks = emit_chunks
    original_decode = module.AudioStreamDecoder._decode

    def decode(self, *args, **kwargs):
        with span('codec.decode'):
            return original_decode(self, *args, **kwargs)

    module.AudioStreamDecoder._decode = decode
    original_encode = module.StreamingTTSDemo._encode_audio_tokens

    def encode(self, *args, **kwargs):
        path = Path(args[0] if args else kwargs['path']).expanduser().resolve()
        emit('voice.source', path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        before = {id(value) for value in self._audio_token_cache.values()}
        with span('voice.prepare'):
            result = original_encode(self, *args, **kwargs)
        emit('voice_cache_hit', hit=id(result) in before)
        return result

    module.StreamingTTSDemo._encode_audio_tokens = encode
    inference = module.MossTTSRealtimeInference
    for name in ('prefill', 'step'):
        original = getattr(inference, name)

        def wrap_model(original, name):
            @functools.wraps(original)
            def model_call(self, *args, **kwargs):
                prefix = kwargs.get('input_ids')
                with span('model.' + name, prefix_length=(len(prefix[0]) if prefix is not None else None)):
                    result = original(self, *args, **kwargs)
                emit('audio_frame', phase=name)
                return result
            return model_call

        setattr(inference, name, wrap_model(original, name))
    import importlib.metadata
    import sys
    emit('service.environment', python=sys.version, conda_prefix=os.environ.get('CONDA_PREFIX'),
         dependencies={name: importlib.metadata.version(name) for name in ('torch', 'transformers')})
    emit('service.config', generation_batch_frames=limit,
         early_compile=os.environ.get('XTALK_TTS_EARLY_COMPILE', '0'),
         missing=['socket_send', 'physical_playback', 'voice_cache_hit_without_prompt'])


def main():
    """Load the fixed adapter and patch its explicit upstream load boundary."""
    if os.environ.get("XTALK_TTS_STACK_DIAGNOSTIC") == "1":
        import faulthandler
        faulthandler.dump_traceback_later(60, repeat=True)
    entrypoint = Path(sys.argv.pop(1)).resolve()
    spec = importlib.util.spec_from_file_location('_xt_moss_adapter', entrypoint)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original_load = module._load_upstream_module

    def load(path):
        upstream = original_load(path)
        apply_service_patch(upstream)
        emit('source', path=str(path), sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
             adapter_sha256=hashlib.sha256(entrypoint.read_bytes()).hexdigest())
        return upstream

    module._load_upstream_module = load
    module.main()


if __name__ == '__main__':
    main()
