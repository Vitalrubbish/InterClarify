"""Stage EOS-closed X2 text and actual 80 ms decode progress."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import threading
import time


class ClosedText:
    """Keep committed text and reject any rewrite before it becomes visible."""

    def __init__(self, decode, join):
        self.decode, self.join = decode, join
        self.parts, self.text, self.count = [], '', 0

    def append(self, ids):
        if not ids or ids[-1] != 2 or any(v in (1, 2, 32, 33) for v in ids[:-1]):
            raise ValueError('Text commit requires a genuine EOS-closed group')
        part = self.decode(ids[:-1]).strip()
        candidate = self.join(self.parts + [part])
        if not candidate.startswith(self.text):
            raise ValueError('Official join attempted to rewrite committed text')
        delta = candidate[len(self.text):]
        self.parts.append(part)
        self.text, self.count = candidate, self.count + 1
        return delta


class IndependentX2:
    """Run a single causal engine; controller states never enter this API."""

    def __init__(self, engine, *, on_text=None, on_progress=None,
                 is_live=lambda: True, clock=time.monotonic, session_id='session', turn_id='turn'):
        self.engine, self.clock, self.is_live = engine, clock, is_live
        self.on_text, self.on_progress = on_text, on_progress
        self.session_id, self.turn_id = session_id, turn_id
        self.frame_index = self.processed_until = self.observed_until = 0
        self.open_tokens, self.closed, self.decoding = [], False, False
        self._feeding = threading.Lock()
        self._publishing = threading.RLock()
        self.text_available_at = self.progress_available_at = None
        self.text_observed_until = 0
        self.failure = None
        self.groups = ClosedText(lambda ids: engine.processor.tokenizer.decode(ids, skip_special_tokens=True), engine.join)
        engine.groups = self.groups

    @classmethod
    def load(cls, model_path, upstream, config_path, **kwargs):
        # Import only the engine, never the historical teacher worker.
        path = Path(__file__).parents[1] / 'remote/x2_streaming_probe.py'
        spec = importlib.util.spec_from_file_location('independent_x2_engine', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = json.loads(Path(config_path).read_text())
        expected = json.loads((Path(__file__).parents[2] / 'configs/x2_streaming_probe.json').read_text())
        if config != expected:
            raise ValueError('Frozen X2 configuration differs')
        model_path, upstream = Path(model_path), Path(upstream)
        for name, digest in config['upstream_files'].items():
            if module.digest(upstream / name) != digest:
                raise ValueError(f'Frozen X2 source differs: {name}')
        if module.digest(model_path / 'model.safetensors') != config['model_sha256']:
            raise ValueError('Frozen X2 weights differ')
        engine = module.X2Engine(model_path, upstream, config)
        with engine.torch.inference_mode():
            startup = engine.reset()
        instance = cls(engine, **kwargs)
        instance.startup = startup
        return instance

    def _token(self, token, phase):
        if phase == 'listen':
            self.decoding = token == 33
        elif phase == 'decode':
            if token not in (1, 2, 32, 33):
                if len(self.open_tokens) >= 64:
                    raise RuntimeError('Open X2 group exceeded 64 text tokens')
                self.open_tokens.append(token)

    def step(self, ledger, step_id):
        if not self._feeding.acquire(blocking=False):
            raise RuntimeError('X2 calls must be serial')
        try:
            if self.closed or not self.is_live():
                raise RuntimeError('X2 is closed')
            started_at = self.clock()
            start, end = self.frame_index * 1280, (self.frame_index + 1) * 1280
            if ledger.eof and start >= ledger.end:
                raise EOFError('No real audio remains for an X2 step')
            audio, spans = ledger.window(start - 200, end + 200)
            previous = self.groups.text
            before_count = self.groups.count
            # step() synchronizes the device before returning; do not acknowledge enqueue.
            with self.engine.torch.inference_mode():
                result = self.engine.step(audio, self._token)
            if result['decision'] not in (32, 33):
                raise ValueError('X2 LISTEN did not produce WAIT or WORD')
            if result['decision'] == 33 and self.groups.count != before_count + 1:
                raise ValueError('WORD did not finish with exactly one closed group')
            if result['decision'] == 32 and self.groups.count != before_count:
                raise ValueError('WAIT unexpectedly changed committed groups')
            self.open_tokens, self.decoding = [], False
            self.processed_until = min(end, ledger.end)
            self.observed_until = min(end + 200, ledger.end)
            common = {'session_id': self.session_id, 'turn_id': self.turn_id,
                      'step_id': step_id, 'frame_index': self.frame_index,
                      'asr_processed_until': self.processed_until,
                      'asr_observed_until': self.observed_until,
                      'committed_groups': self.groups.count}
            with self._publishing:
                if self.closed or not self.is_live():
                    raise RuntimeError('X2 completed after cancellation')
                if self.groups.text != previous:
                    self.text_available_at = self.clock()
                    self.text_observed_until = self.observed_until
                    if self.on_text:
                        self.on_text(dict(common, text=self.groups.text, delta=self.groups.text[len(previous):],
                                          source='x2_streaming_asr', text_available_at=self.text_available_at,
                                          text_observed_until=self.text_observed_until))
            self.progress_available_at = self.clock()
            progress = dict(common, asr_progress_available_at=self.progress_available_at,
                            decoding=False, open_group_tokens=[], decision=result['decision'])
            with self._publishing:
                if not self.closed and self.is_live() and self.on_progress:
                    self.on_progress(deepcopy(progress))
            self.frame_index += 1
            return dict(progress, lane='asr', started_at=started_at, completed_at=self.clock(), input_spans=spans,
                        input_sha256=ledger.digest(audio), text=self.groups.text,
                        text_observed_until=self.text_observed_until, text_available_at=self.text_available_at)
        except Exception as exc:
            self.closed, self.failure = True, str(exc)
            raise
        finally:
            self._feeding.release()

    def cancel(self):
        with self._publishing:
            self.closed = True

    def diagnostics(self):
        return {'decoded_text': self.groups.text, 'decoded_groups': self.groups.count,
                'processed_until': self.processed_until, 'observed_until': self.observed_until,
                'open_group_tokens': list(self.open_tokens), 'decoding': self.decoding,
                'tail_status': 'unknown', 'closed': self.closed, 'failure': self.failure}
