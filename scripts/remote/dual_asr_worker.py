"""Serve bounded independent RNNT completions without a publication barrier."""
from collections import deque
import argparse
import base64
import json
from pathlib import Path
import socket
import threading
import time
import uuid

import numpy as np

from nemotron_asr_service import AudioBuffer, NemotronSession, NemotronService, load_pcm16
from nemotron_teacher_worker import SynchronizedNemotron, GENERATION_SHA256


class UnreadAudioBuffer(AudioBuffer):
    """Bound genuinely unread PCM separately from the native overlap window."""

    def __init__(self):
        super().__init__(max_pending_seconds=.8, drain_seconds=0)
        self.peak_unread = self.peak_bytes = 0
        self.read_started_at = self.read_ready_at = None

    def append(self, pcm, eof=False):
        if len(pcm) % 2:
            raise ValueError('PCM16 requires an even byte count')
        samples = np.frombuffer(pcm, '<i2').astype(np.float32) / 32768
        with self.condition:
            if self.eof or self.cancelled:
                raise ValueError('Stream is closed')
            unread = self.received + len(samples) - self.consumed
            size = self.pcm.nbytes + samples.nbytes
            if unread > self.max_pending:
                raise RuntimeError('Nemotron unread audio exceeded 800ms')
            if size > 131072:
                raise RuntimeError('Nemotron retained PCM byte limit exceeded')
            self.pcm = np.concatenate((self.pcm, samples))
            self.received += len(samples)
            self.eof = eof
            self.peak_unread, self.peak_bytes = max(self.peak_unread, unread), max(self.peak_bytes, size)
            self.condition.notify_all()

    def read(self, start, size):
        with self.condition:
            self.read_started_at = time.monotonic()
            while not self.cancelled:
                if start < self.offset:
                    raise RuntimeError('Feature generator requested discarded PCM')
                if start + size <= self.received:
                    begin = start - self.offset
                    result = self.pcm[begin:begin + size].copy()
                    self.consumed = start + size
                    self.read_ready_at = time.monotonic()
                    discard = max(0, begin - 1024)
                    self.pcm = self.pcm[discard:].copy()
                    self.offset += discard
                    return result
                if self.eof:
                    return None
                self.condition.wait(.05)
            raise InterruptedError('Stream cancelled')

    def metrics(self):
        with self.condition:
            return {'unread_samples': self.received - self.consumed,
                    'retained_pcm_bytes': self.pcm.nbytes,
                    'read_retained_samples': max(0, self.consumed - self.offset),
                    'read_started_at': self.read_started_at, 'read_ready_at': self.read_ready_at,
                    'peak_unread_samples': self.peak_unread, 'peak_retained_pcm_bytes': self.peak_bytes}


class IndependentSession(NemotronSession):
    """Keep only bounded uncollected completion records; decoding never waits."""

    def __init__(self, engine):
        self.id = uuid.uuid4().hex
        self.source = UnreadAudioBuffer()
        self.lock = threading.Lock()
        self.text = self.raw = ''
        self.ids = []
        self.version = self.step_seq = self.step_bytes = self.collected = 0
        self.error = None
        self.done = threading.Event()
        self.started = time.monotonic()
        self.steps = deque()
        self.worker = threading.Thread(target=self._run, args=(engine,), daemon=True)
        self.worker.start()

    def emit(self, text, ids):
        with self.lock:
            if not text.startswith(self.text):
                raise RuntimeError('Native transcript rewrote a delivered prefix')
            if len(text) > 65536 or len(ids) > 65536:
                raise RuntimeError('Native transcript hard limit exceeded')
            self.version += int(text != self.text)
            self.text = self.raw = text
            self.ids = ids

    def complete_step(self, step):
        with self.lock:
            if step['step_seq'] != self.step_seq + 1:
                raise ValueError('Decoder steps must be contiguous')
            event = dict(step, text=self.text, generation=self.id,
                         prefix_version=self.version, pcm=self.source.metrics())
            size = len(json.dumps(event, ensure_ascii=False, allow_nan=False).encode())
            if len(self.steps) >= 16 or self.step_bytes + size > 1048576:
                raise RuntimeError('Native completion queue hard limit exceeded')
            self.steps.append((event, size))
            self.step_bytes += size
            self.step_seq = step['step_seq']

    def read_steps(self, after=0):
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            if after < self.collected or after > self.step_seq:
                raise ValueError('Invalid native collection cursor')
            while self.steps and self.steps[0][0]['step_seq'] <= after:
                _, size = self.steps.popleft()
                self.step_bytes -= size
            self.collected = after
            return {'steps': [dict(v) for v, _ in self.steps], 'ended': self.done.is_set(),
                    'last_step_seq': self.step_seq, 'pcm': self.source.metrics(), 'text': self.text}


def main():
    parser = argparse.ArgumentParser()
    for name in ('model', 'warmup-audio', 'socket', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.55, 0)
    engine = SynchronizedNemotron(args.model)
    service = NemotronService(engine, timeout=10)
    service.warmup(load_pcm16(args.warmup_audio), timeout=120)
    args.output.write_text(json.dumps({'engine': engine.info, 'generation_sha256': GENERATION_SHA256,
                                     'barrier': False, 'ready_at': time.monotonic()}) + '\n')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(args.socket))
        args.socket.chmod(0o600)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                try:
                    line = connection.makefile('rb').readline(1048576)
                    if not line.endswith(b'\n'):
                        raise ValueError('Incomplete or oversized RPC')
                    request = json.loads(line)
                    operation = request['operation']
                    if operation == 'create':
                        if service.session is not None:
                            raise ValueError('One stream at a time')
                        service.session = IndependentSession(engine)
                        response = {'session_id': service.session.id}
                    elif operation == 'close':
                        service.close(request['session_id'])
                        response = {'ok': True}
                    else:
                        session = service.get(request['session_id'])
                        if operation == 'push':
                            session.source.append(base64.b64decode(request.get('audio', ''), validate=True),
                                                  eof=request.get('eof', False))
                            response = session.snapshot()
                        elif operation == 'poll':
                            response = session.read_steps(request['after'])
                        else:
                            raise ValueError('Unknown operation')
                except Exception as exc:
                    response = {'error': f'{type(exc).__name__}: {exc}'}
                connection.sendall(json.dumps(response, allow_nan=False).encode() + b'\n')


if __name__ == '__main__':
    main()
