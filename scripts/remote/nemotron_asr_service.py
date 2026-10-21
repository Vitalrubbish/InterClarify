"""Serve native Nemotron EN RNNT generation with one isolated live stream."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
import uuid

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

LOG = logging.getLogger(__name__)


def load_pcm16(path):
    """Normalize PCM or float WAV to little-endian PCM16 without rewriting input."""
    import soundfile as sf
    audio, rate = sf.read(str(path), dtype='float32', always_2d=True)
    if rate != 16000 or audio.shape[1] != 1 or not np.isfinite(audio).all():
        raise ValueError('Input must be finite mono 16kHz audio')
    return (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()


class AudioBuffer:
    """Bound retained PCM while a generator waits for genuinely arrived samples."""

    def __init__(self, max_pending_seconds=30, drain_seconds=2):
        self.condition = threading.Condition()
        self.pcm = np.empty(0, dtype=np.float32)
        self.offset = 0
        self.received = 0
        self.consumed = 0
        self.max_pending = int(max_pending_seconds * 16000)
        self.drain = int(drain_seconds * 16000)
        self.eof = False
        self.cancelled = False

    def append(self, pcm: bytes, eof=False):
        """Append PCM16 once; EOF adds explicitly accounted decoder-only silence."""
        if len(pcm) % 2:
            raise ValueError('PCM16 requires an even byte count')
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        with self.condition:
            if self.eof or self.cancelled:
                raise ValueError('Stream is closed')
            if len(self.pcm) + len(samples) > self.max_pending:
                raise ValueError('Audio backlog exceeds configured limit')
            self.received += len(samples)
            self.pcm = np.concatenate((self.pcm, samples, np.zeros(self.drain) if eof else [] )).astype(np.float32)
            self.eof = eof
            self.condition.notify_all()

    def read(self, start, size):
        """Wait for a full feature window, retaining only its overlap for next read."""
        end = start + size
        with self.condition:
            while not self.cancelled:
                available = self.offset + len(self.pcm)
                if start < self.offset:
                    raise RuntimeError('Feature generator requested discarded PCM')
                if self.eof and start >= available:
                    return None
                if end <= available or self.eof:
                    begin = start - self.offset
                    value = self.pcm[begin:begin + size].copy()
                    self.consumed = min(end, self.received)
                    # Keep one FFT overlap; subsequent feature windows advance monotonically.
                    discard = max(0, begin - 1024)
                    self.pcm = self.pcm[discard:]
                    self.offset += discard
                    return np.pad(value, (0, size - len(value)))
                self.condition.wait(timeout=0.1)
            raise InterruptedError('Stream cancelled')

    def cancel(self):
        """Wake a generator blocked on an input window."""
        with self.condition:
            self.cancelled = True
            self.condition.notify_all()


class NativeNemotron:
    """Keep model weights fixed while generate owns its native RNNT caches."""

    def __init__(self, model_path):
        started = time.monotonic()
        import torch
        from transformers import AutoModelForRNNT, AutoProcessor
        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.processor.set_num_lookahead_tokens(1)
        self.model = AutoModelForRNNT.from_pretrained(model_path, local_files_only=True,
                                                     dtype=torch.float32).to('cuda').eval()
        self.info = {'backend': 'nemotron_en', 'model': str(Path(model_path).resolve()),
                     'chunk_ms': 160, 'dtype': str(self.model.dtype),
                     'torch': torch.__version__, 'load_seconds': time.monotonic()-started}

    def run(self, source, emit):
        """Feed the released processor's overlapping, cache-aware feature iterator."""
        torch, processor, model = self.torch, self.processor, self.model
        extra = {}

        def features():
            first = True
            frame_index = 0
            while True:
                start = 0 if first else frame_index * processor.feature_extractor.hop_length - processor.feature_extractor.n_fft // 2
                size = processor.num_samples_first_audio_chunk if first else processor.num_samples_per_audio_chunk
                audio = source.read(start, size)
                if audio is None:
                    return
                inputs = processor(audio, sampling_rate=16000, is_streaming=True,
                                   is_first_audio_chunk=first, return_tensors='pt')
                if first:
                    extra.update({k: v.to('cuda') if torch.is_tensor(v) else v
                                  for k, v in inputs.items()
                                  if k not in ('input_features', 'attention_mask', 'num_lookahead_tokens')})
                frames = processor.num_mel_frames_first_audio_chunk if first else processor.num_mel_frames_per_audio_chunk
                yield inputs.input_features[:, :frames].to('cuda', dtype=model.dtype)
                frame_index += frames
                first = False

        class Recorder:
            """Decode original emitted IDs, preserving word-internal increments."""

            def __init__(self):
                self.ids = []

            def put(self, value):
                self.ids.extend(value.detach().cpu().reshape(-1).tolist())
                emit(processor.decode(self.ids, skip_special_tokens=True,
                                      clean_up_tokenization_spaces=False), list(self.ids))

            def end(self):
                pass

        with torch.inference_mode():
            generator = features()
            try:
                first = next(generator)
            except StopIteration:
                return
            def all_features():
                yield first
                yield from generator
            model.generate(input_features=all_features(), num_lookahead_tokens=1,
                           streamer=Recorder(), do_sample=False,
                           return_dict_in_generate=True, **extra)


class NemotronSession:
    """Own a generation UUID, bounded audio, transcript and terminal worker state."""

    def __init__(self, engine):
        self.id = uuid.uuid4().hex
        self.source = AudioBuffer()
        self.lock = threading.Lock()
        self.text = ''
        self.raw = ''
        self.ids = []
        self.version = 0
        self.error = None
        self.done = threading.Event()
        self.started = time.monotonic()
        self.worker = threading.Thread(target=self._run, args=(engine,), daemon=True)
        self.worker.start()

    def emit(self, text, ids):
        """Reject rewrites before delivery instead of silently freezing prefixes."""
        with self.lock:
            self.raw, self.ids = text, ids
            if not text.startswith(self.text):
                raise RuntimeError('Native transcript rewrote an already delivered prefix')
            if text != self.text:
                delta = text[len(self.text):]
                self.version += 1
                self.text = text
                LOG.info(json.dumps({'event': 'asr_output', 'session_id': self.id,
                    'generation': self.id, 'prefix_version': self.version, 'raw': text,
                    'visible': text, 'delta': delta, 'arrival_monotonic': time.monotonic(),
                    'received_samples': self.source.received, 'consumed_samples': self.source.consumed}))

    def _run(self, engine):
        try:
            engine.run(self.source, self.emit)
        except Exception as exc:
            if not self.source.cancelled:
                self.error = repr(exc)
                LOG.exception('Native ASR failed session=%s', self.id)
        finally:
            self.done.set()

    def snapshot(self):
        """Read output independently of new audio; fail closed on decoder errors."""
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            return {'session_id': self.id, 'generation': self.id, 'text': self.text,
                    'raw_text': self.raw, 'prefix_version': self.version,
                    'ended': self.done.is_set(), 'received_samples': self.source.received,
                    'consumed_samples': self.source.consumed}


class NemotronService:
    """Serialize GPU stream ownership; quarantine workers that fail to terminate."""

    def __init__(self, engine, timeout=30):
        self.engine, self.timeout = engine, timeout
        self.lock = threading.RLock()
        self.session = None
        self.ready = False

    def create(self):
        """Allocate an isolated native generation without replacing a live session."""
        with self.lock:
            if self.session is not None:
                raise RuntimeError('Only one active stream is supported')
            self.session = NemotronSession(self.engine)
            return self.session.id

    def get(self, identity):
        """Reject unknown and previously cancelled generation IDs."""
        with self.lock:
            if self.session is None or self.session.id != identity:
                raise KeyError(identity)
            return self.session

    def close(self, identity):
        """Cancel input, join native generation and release ownership only on exit."""
        with self.lock:
            session = self.get(identity)
            started = time.monotonic()
            session.source.cancel()
            session.worker.join(self.timeout)
            if session.worker.is_alive():
                self.ready = False
                raise RuntimeError('Cancelled worker did not terminate; service quarantined')
            self.session = None
            LOG.info(json.dumps({'event': 'asr_closed', 'session_id': identity,
                                 'reason': 'eof' if session.source.eof else 'cancel',
                                 'release_seconds': time.monotonic()-started,
                                 'at_monotonic': time.monotonic()}))

    def warmup(self, pcm, timeout=None):
        """Require real speech output and cleanup for two sequential sessions."""
        if not pcm or len(pcm) % 2 or not np.any(np.frombuffer(pcm, dtype='<i2')):
            raise ValueError('Warmup requires non-silent PCM16 speech')
        for _ in range(2):
            identity = self.create()
            session = self.get(identity)
            try:
                session.source.append(pcm, eof=True)
                if not session.done.wait(self.timeout if timeout is None else timeout):
                    raise RuntimeError('ASR warmup timed out')
                result = session.snapshot()
                if not result['text'].strip():
                    raise RuntimeError('ASR warmup produced no text')
                LOG.info(json.dumps({'event': 'asr_warmup', **result,
                    'audio_sha256': hashlib.sha256(pcm).hexdigest()}))
            finally:
                self.close(identity)
        self.ready = True


class RecognizeRequest(BaseModel):
    """Transport PCM separately from the 160ms model feature window."""

    session_id: str
    audio: str = ''
    is_final: bool = False
    end_stream: bool = False


def create_app(service):
    """Expose bounded single-stream transport; temporary pauses are inert."""
    app = FastAPI()

    @app.exception_handler(KeyError)
    async def unknown(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={'detail': 'Unknown stream generation'})

    @app.get('/health')
    def health():
        import resource
        if not service.ready:
            raise HTTPException(503, 'Warmup not completed')
        return {'status': 'ok', **service.engine.info, 'warmup_sessions': 2, 'offline': False,
                'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}

    @app.post('/v1/session')
    def create():
        try:
            identity = service.create()
            return {'session_id': identity, 'generation': identity}
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/v1/session/{identity}/result')
    def read(identity: str):
        try:
            return service.get(identity).snapshot()
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post('/v1/recognize')
    def recognize(request: RecognizeRequest):
        session = service.get(request.session_id)
        try:
            pcm = base64.b64decode(request.audio, validate=True)
            if pcm or request.end_stream:
                session.source.append(pcm, eof=request.end_stream)
            LOG.info(json.dumps({'event': 'asr_input', 'session_id': session.id,
                'received_monotonic': time.monotonic(), 'bytes': len(pcm),
                'sha256': hashlib.sha256(pcm).hexdigest(), 'pause': request.is_final,
                'eof': request.end_stream, 'pending_samples': len(session.source.pcm)}))
            if request.end_stream and not session.done.wait(service.timeout):
                raise RuntimeError('Native EOF drain timeout')
            return session.snapshot()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.delete('/v1/session/{identity}')
    def close(identity: str):
        try:
            service.close(identity)
            return {'ok': True}
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
    return app


def main():
    """Load the fixed local EN model and publish readiness after speech warmup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--warmup-audio', type=Path, required=True)
    parser.add_argument('--warmup-timeout', type=float, default=30)
    parser.add_argument('--port', type=int, default=8005)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    pcm = load_pcm16(args.warmup_audio)
    LOG.info(json.dumps({'event':'warmup_source', 'source_sha256':hashlib.sha256(args.warmup_audio.read_bytes()).hexdigest(),
                         'pcm16_sha256':hashlib.sha256(pcm).hexdigest()}))
    engine = NativeNemotron(str(args.model))
    service = NemotronService(engine)
    if not np.isfinite(args.warmup_timeout) or args.warmup_timeout <= 0:
        parser.error('warmup-timeout must be positive and finite')
    service.warmup(pcm, timeout=args.warmup_timeout)
    import uvicorn
    uvicorn.run(create_app(service), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
