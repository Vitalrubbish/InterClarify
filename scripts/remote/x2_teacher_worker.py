"""Serve ordered two-frame X2 teacher steps with bounded publication lookahead."""
from __future__ import annotations

import argparse
import base64
from collections import deque
import json
from pathlib import Path
import socket
import threading
import time
import traceback
import uuid

from nemotron_asr_service import AudioBuffer, load_pcm16
from x2_streaming_probe import X2Engine, digest, run_stream, write_json


class X2Session:
    """One cancellable decoder and one contiguous, bounded RPC step cursor."""

    def __init__(self, engine):
        self.engine = engine
        self.id = uuid.uuid4().hex
        self.source = AudioBuffer(max_pending_seconds=.8, drain_seconds=0)
        self.steps = deque(maxlen=4096)
        self.seq, self.released = 0, 0
        self.text, self.error, self.metrics = '', None, {}
        self.done = threading.Event()
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def run(self):
        import numpy as np
        engine, source = self.engine, self.source
        elapsed, frames, pending, pair_started = 0., 0, [], None
        try:
            with engine.torch.inference_mode():
                engine.reset()
                while True:
                    start = max(0, frames * 1280 - 200)
                    window = source.read(start, 1480 if frames == 0 else 1680)
                    if window is None:
                        break
                    with source.condition:
                        if frames * 1280 >= source.received:
                            break
                        consumed = source.consumed
                    if frames == 0:
                        window = np.concatenate((np.zeros(200, np.float32), window))
                    began = time.monotonic()
                    if not pending:
                        pair_started = began
                    record = engine.step(window, lambda *_: None)
                    elapsed += record['compute_ms'] / 1000
                    frames += 1
                    pending.append(record)
                    self.text = engine.groups.text
                    if len(pending) == 2:
                        self.publish({'step_seq': self.seq + 1, 'text': self.text,
                            'decode_started_at': pair_started,
                            'decode_completed_at': time.monotonic(), 'consumed_samples': consumed,
                            'received_samples': source.received, 'eof_received': source.eof,
                            'main_audio_end_sample': frames * 1280,
                            'next_feature_end_sample': (frames + 2) * 1280 + 200,
                            'x2_frames_consumed': 2, 'x2_open_group_tokens': 0,
                            'x2_closed_groups': sum(f['closed_groups'] for f in pending),
                            'x2_frame_tokens': [f['token_ids'] for f in pending],
                            'x2_compute_seconds_total': elapsed, 'x2_frames_total': frames})
                        pending = []
        except Exception:
            if not source.cancelled:
                self.error = traceback.format_exc()
                traceback.print_exc()
        finally:
            with source.condition:
                self.metrics = {'frames': frames, 'compute_seconds': elapsed,
                    'x2_rtf': elapsed / (source.received / 16000) if source.received else None,
                    'unpublished_frames': len(pending), 'text': self.text,
                    'peak_gpu_mib': max(engine.memory_samples, default=0)}
                self.done.set()
                source.condition.notify_all()

    def publish(self, step):
        with self.source.condition:
            self.seq += 1
            if step['step_seq'] != self.seq:
                raise ValueError('X2 decoder sequence is not contiguous')
            self.steps.append(step)
            deadline = time.monotonic() + 5
            while self.seq - self.released >= 4 and not self.source.eof and not self.source.cancelled:
                if time.monotonic() >= deadline:
                    raise TimeoutError('X2 publication barrier timed out')
                self.source.condition.wait(.1)
            if self.source.cancelled:
                raise InterruptedError('X2 session cancelled')

    def poll(self, after):
        with self.source.condition:
            if self.error:
                raise RuntimeError(self.error)
            if not 0 <= after <= self.seq or (self.steps and after < self.steps[0]['step_seq'] - 1):
                raise ValueError('Invalid X2 step cursor')
            return {'steps': [s.copy() for s in self.steps if s['step_seq'] > after],
                    'ended': self.done.is_set(), 'metrics': self.metrics}

    def release(self, seq, published_at):
        with self.source.condition:
            if seq != self.released + 1 or seq > self.seq:
                raise ValueError('X2 releases must be contiguous')
            step = next(s for s in self.steps if s['step_seq'] == seq)
            if not step['decode_completed_at'] <= published_at <= time.monotonic():
                raise ValueError('Invalid X2 publication timestamp')
            self.released = seq
            self.source.condition.notify_all()
            return {'released_at': time.monotonic(), 'step_seq': seq}

    def close(self):
        self.source.cancel()
        self.worker.join(10)
        if self.worker.is_alive():
            raise RuntimeError('X2 cancelled worker did not terminate')


def main():
    parser = argparse.ArgumentParser()
    for name in ('model', 'upstream', 'config', 'warmup-audio', 'socket', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    config = json.loads(args.config.read_text())
    if digest(args.model / 'model.safetensors') != config['model_sha256']:
        raise ValueError('X2 model digest differs')
    for name, expected in config['upstream_files'].items():
        if digest(args.upstream / name) != expected:
            raise ValueError('X2 upstream source digest differs: ' + name)
    torch.cuda.set_per_process_memory_fraction(.55, 0)
    engine = X2Engine(args.model, args.upstream, config)
    pcm = load_pcm16(args.warmup_audio)
    audio = np.frombuffer(pcm, '<i2').astype(np.float32) / 32768
    output = args.output.parent / 'x2_warmup'
    output.mkdir()
    warmup = [run_stream(engine, audio, f'warmup_{i}', output, realtime=False) for i in range(2)]
    if not all(w['online_text'].strip() for w in warmup):
        raise ValueError('X2 speech warmup produced no text')
    write_json(args.output, {'warmup_sessions': warmup, 'warmup_audio_sha256': digest(args.warmup_audio),
                            'ready_at': time.monotonic(), 'config': config})
    session = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(args.socket))
        args.socket.chmod(0o600)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                try:
                    line = connection.makefile('rb').readline(1024 * 1024)
                    if not line.endswith(b'\n'):
                        raise ValueError('Oversized or incomplete X2 RPC')
                    request = json.loads(line)
                    op = request['operation']
                    if op == 'create':
                        if session is not None:
                            raise ValueError('Only one X2 stream is supported')
                        session = X2Session(engine)
                        response = {'session_id': session.id}
                    else:
                        if session is None or request['session_id'] != session.id:
                            raise ValueError('Unknown X2 session')
                        if op == 'push':
                            session.source.append(base64.b64decode(request.get('audio', ''), validate=True),
                                                  eof=request.get('eof', False))
                            response = {'ok': True}
                        elif op == 'poll':
                            response = session.poll(request['after'])
                        elif op == 'release':
                            response = session.release(request['step_seq'], request['published_at'])
                        elif op == 'close':
                            session.close()
                            session = None
                            response = {'ok': True}
                        else:
                            raise ValueError('Unknown X2 RPC operation')
                except Exception as exc:
                    response = {'error': f'{type(exc).__name__}: {exc}'}
                connection.sendall(json.dumps(response, allow_nan=False).encode() + b'\n')


if __name__ == '__main__':
    main()
