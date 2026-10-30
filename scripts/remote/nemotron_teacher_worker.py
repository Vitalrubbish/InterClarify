"""Serve RNNT steps with a publication barrier before the next feature read."""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import inspect
import json
from pathlib import Path
import socket
import textwrap
import time

from nemotron_asr_service import NativeNemotron, NemotronSession, NemotronService, load_pcm16

GENERATION_SHA256 = 'c45e19eb4534a2478f8e4825dc35a28fb5efe5a2f8d09695e4b2ea532b4dbd82'


def reorder_sample(source):
    """Deliver the selected token before kwargs update can request another chunk."""
    tree = ast.parse(textwrap.dedent(source))
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    matches = []
    for loop in loops:
        updates = [n for n in loop.body if isinstance(n, ast.Assign)
                   and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                   and n.value.func.attr == '_update_model_kwargs_for_generation']
        deliveries = [n for n in loop.body if isinstance(n, ast.If)
                      and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                              and isinstance(c.func.value, ast.Name) and c.func.value.id == 'streamer'
                              and c.func.attr == 'put' for c in ast.walk(n))]
        if len(updates) == len(deliveries) == 1:
            update, delivery = updates[0], deliveries[0]
            if loop.body.index(update) >= loop.body.index(delivery):
                raise ValueError('Generation order already differs from audited source')
            loop.body.remove(update)
            loop.body.insert(loop.body.index(delivery) + 1, update)
            matches.append(loop)
    if len(matches) != 1:
        raise ValueError('Expected exactly one generation update and streamer delivery')
    return ast.fix_missing_locations(tree)


def synchronized_sample(model):
    from transformers.generation.utils import GenerationMixin
    method = GenerationMixin._sample
    path = Path(inspect.getfile(method))
    if hashlib.sha256(path.read_bytes()).hexdigest() != GENERATION_SHA256:
        raise ValueError('Transformers generation source digest differs')
    namespace = dict(method.__globals__)
    exec(compile(reorder_sample(inspect.getsource(method)), str(path) + ':teacher-barrier', 'exec'), namespace)
    return namespace['_sample']


class SynchronizedNemotron(NativeNemotron):
    """Keep native caches while pausing at a real completed feature chunk."""

    def run(self, source, emit, emit_step=None):
        torch, processor, model = self.torch, self.processor, self.model
        extra = {}

        def features():
            first, frame_index, seq = True, 0, 0
            while True:
                start = 0 if first else frame_index * processor.feature_extractor.hop_length - processor.feature_extractor.n_fft // 2
                size = processor.num_samples_first_audio_chunk if first else processor.num_samples_per_audio_chunk
                audio = source.read(start, size)
                if audio is None:
                    return
                inputs = processor(audio, sampling_rate=16000, is_streaming=True,
                                   is_first_audio_chunk=first, return_tensors='pt')
                if first:
                    extra.update({k: v.to('cuda') if torch.is_tensor(v) else v for k, v in inputs.items()
                                  if k not in ('input_features', 'attention_mask', 'num_lookahead_tokens')})
                frames = processor.num_mel_frames_first_audio_chunk if first else processor.num_mel_frames_per_audio_chunk
                seq += 1
                step = {'step_seq': seq, 'feature_start_sample': start, 'feature_end_sample': start + size,
                        'consumed_samples': source.consumed, 'received_samples': source.received,
                        'nominal_audio_start_ms': (seq - 1) * 160, 'nominal_audio_end_ms': seq * 160,
                        'decode_started_at': time.monotonic(), 'eof_received': source.eof}
                yield inputs.input_features[:, :frames].to('cuda', dtype=model.dtype)
                torch.cuda.synchronize()
                step['decode_completed_at'] = time.monotonic()
                if emit_step:
                    emit_step(step)
                frame_index += frames
                first = False

        class Recorder:
            def __init__(self):
                self.ids = []

            def put(self, value):
                self.ids.extend(value.detach().cpu().reshape(-1).tolist())
                emit(processor.decode(self.ids, skip_special_tokens=True,
                                      clean_up_tokenization_spaces=False), list(self.ids))

            def end(self):
                pass

        model_type = type(model)
        override = model_type.__dict__.get('_sample')
        model_type._sample = synchronized_sample(model)
        try:
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
        finally:
            if override is None:
                del model_type._sample
            else:
                model_type._sample = override


class BarrierSession(NemotronSession):
    """Wait for the matching Context publication without blocking audio ingress."""

    def __init__(self, engine):
        self.released_seq = 0
        self.released_at = None
        super().__init__(engine)
        self.source.max_pending = 12800

    def complete_step(self, step):
        step = dict(step, previous_released_at=self.released_at)
        super().complete_step(step)
        with self.source.condition:
            deadline = time.monotonic() + 5
            while self.released_seq < step['step_seq'] and not self.source.eof and not self.source.cancelled:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Teacher publication barrier timed out')
                self.source.condition.wait(min(remaining, .1))
            if self.source.cancelled:
                raise InterruptedError('Teacher stream cancelled at barrier')

    def release(self, seq, published_at):
        with self.source.condition:
            if seq != self.released_seq + 1 or seq != self.step_seq:
                raise ValueError('Release must acknowledge exactly the pending decoder step')
            if not self.steps[-1]['decode_completed_at'] <= published_at <= time.monotonic():
                raise ValueError('Invalid Context publication timestamp')
            self.released_seq, self.released_at = seq, time.monotonic()
            self.source.condition.notify_all()
            return {'released_at': self.released_at, 'step_seq': seq}


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
                                       'warmup_sessions': 2, 'ready_at': time.monotonic()}) + '\n')
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
                        raise ValueError('Oversized or incomplete RPC')
                    request = json.loads(line)
                    operation = request['operation']
                    if operation == 'create':
                        if service.session is not None:
                            raise ValueError('One stream at a time')
                        service.session = BarrierSession(engine)
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
                        elif operation == 'release':
                            response = session.release(request['step_seq'], request['published_at'])
                        else:
                            raise ValueError('Unknown operation')
                except Exception as exc:
                    response = {'error': f'{type(exc).__name__}: {exc}'}
                connection.sendall(json.dumps(response, allow_nan=False).encode() + b'\n')


if __name__ == '__main__':
    main()
