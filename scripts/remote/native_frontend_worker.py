"""Isolate the independent X2 engine in its pinned ASR conda environment."""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from independent_x2 import IndependentX2
from native_soulx import pcm_digest

MAX_MESSAGE = 256 * 1024


def send(connection, value):
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n'
    if len(payload) > MAX_MESSAGE:
        raise ValueError('IPC message exceeds 256 KiB')
    connection.sendall(payload)


def receive(stream):
    line = stream.readline(MAX_MESSAGE + 1)
    if not line.endswith(b'\n') or len(line) > MAX_MESSAGE:
        raise ValueError('IPC message is incomplete or oversized')
    result = json.loads(line)
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result


class WindowLedger:
    """Expose exactly one verified PCM window to the isolated decoder."""

    digest = staticmethod(pcm_digest)

    def __init__(self, request):
        self.begin, self.end, self.eof = request['begin'], request['end'], request['eof']
        self.audio = np.frombuffer(base64.b64decode(request['audio'], validate=True), dtype='<f4')
        self.spans = request['spans']
        if (len(self.audio) != 1680 or not np.isfinite(self.audio).all()
                or sum(row['samples'] for row in self.spans) != 1680
                or pcm_digest(self.audio) != request['sha256']):
            raise ValueError('IPC audio integrity failed')

    def window(self, begin, end):
        if begin != self.begin or end - begin != len(self.audio):
            raise ValueError('Decoder requested PCM outside the supplied window')
        return self.audio, deepcopy(self.spans)


class X2Process:
    """Own one bounded synchronous decoder process and its session proxy."""

    def __init__(self, python, assets, output):
        assets, output = Path(assets), Path(output)
        parent, child = socket.socketpair()
        self.connection, self.stream = parent, parent.makefile('rb')
        self.log = (output / 'x2_worker.log').open('x')
        try:
            self.process = subprocess.Popen([
                str(python), '-B', str(Path(__file__).resolve()), '--fd', str(child.fileno()),
                '--assets', str(assets)], pass_fds=(child.fileno(),), stdout=self.log, stderr=subprocess.STDOUT)
        except BaseException:
            parent.close()
            self.stream.close()
            self.log.close()
            raise
        finally:
            child.close()
        parent.settimeout(300)
        try:
            self.ready = receive(self.stream)
        except BaseException:
            self.close()
            raise
        parent.settimeout(30)

    def request(self, operation, **kwargs):
        send(self.connection, dict(operation=operation, **kwargs))
        return receive(self.stream)

    def session(self, session_id, turn_id):
        startup = self.request('create', session_id=session_id, turn_id=turn_id)
        return RemoteX2(self, session_id, turn_id, startup)

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(5)
        finally:
            self.stream.close()
            self.connection.close()
            self.log.close()


class RemoteX2:
    """Stage callbacks locally while retaining actual device completion times."""

    def __init__(self, worker, session_id, turn_id, startup):
        self.worker, self.session_id, self.turn_id = worker, session_id, turn_id
        self.startup = startup
        self.on_text = self.on_progress = None
        self.is_live = lambda: True
        self.frame_index = self.processed_until = self.observed_until = 0
        self.closed = False
        self.last = {'decoded_text': '', 'decoded_groups': 0, 'open_group_tokens': [],
                     'processed_until': 0, 'observed_until': 0, 'decoding': False,
                     'tail_status': 'unknown'}

    def step(self, ledger, step_id):
        if self.closed or not self.is_live():
            raise RuntimeError('Remote decoder is closed')
        begin = self.frame_index * 1280 - 200
        audio, spans = ledger.window(begin, begin + 1680)
        sent_at = time.monotonic()
        result = self.worker.request('step', step_id=step_id, begin=begin, end=ledger.end,
            eof=ledger.eof, spans=spans, sha256=pcm_digest(audio),
            audio=base64.b64encode(audio.astype('<f4', copy=False).tobytes()).decode())
        received_at = time.monotonic()
        self.last = result['diagnostics']
        if self.closed or not self.is_live():
            raise RuntimeError('Remote decoder completed after cancellation')
        for kind, callback in (('text', self.on_text), ('progress', self.on_progress)):
            for row in result[kind]:
                if callback:
                    callback(row)
        row = result['receipt']
        if row['frame_index'] != self.frame_index:
            raise ValueError('Remote decoder frame cursor differs')
        self.frame_index += 1
        self.processed_until, self.observed_until = row['asr_processed_until'], row['asr_observed_until']
        row.update(ipc_sent_at=sent_at, ipc_received_at=received_at,
                   ipc_seconds=received_at - sent_at - (row['completed_at'] - row['started_at']))
        return row

    def cancel(self):
        self.closed = True

    def diagnostics(self):
        return dict(self.last, closed=self.closed)


def profile_engine(engine):
    """Time synchronized audio encoding and LM work without changing outputs."""
    engine.stage_records = []
    for name in ('encode', 'lm'):
        original = getattr(engine, name)

        def measured(*args, _name=name, _method=original, **kwargs):
            started = time.monotonic()
            result = _method(*args, **kwargs)
            engine.torch.cuda.synchronize()
            engine.stage_records.append({'name': _name, 'started_at': started, 'completed_at': time.monotonic()})
            return result
        setattr(engine, name, measured)


def serve(args):
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    connection = socket.socket(fileno=args.fd)
    stream = connection.makefile('rb')
    asr = IndependentX2.load(args.assets / 'models/x2streaming-asr',
        args.assets / 'upstream/frozen-20261028/x2streaming-asr',
        Path(__file__).parents[2] / 'configs/x2_streaming_probe.json')
    engine = asr.engine
    profile_engine(engine)
    if torch.get_num_threads() != 2 or torch.get_num_interop_threads() != 1:
        raise RuntimeError('X2 initialization changed the CPU thread budget')
    send(connection, {'loaded_at': time.monotonic(), 'startup': asr.startup,
                      'cpu_threads': torch.get_num_threads(),
                      'interop_threads': torch.get_num_interop_threads()})
    asr = None
    while True:
        try:
            request = receive(stream)
            if request['operation'] == 'create':
                if asr is not None:
                    raise RuntimeError('Previous X2 session was not cleared')
                torch.manual_seed(42)
                np.random.seed(42)
                with torch.inference_mode():
                    startup = engine.reset()
                asr = IndependentX2(engine, session_id=request['session_id'], turn_id=request['turn_id'])
                engine.stage_records.clear()
                response = {'startup': startup, 'clean_text': not asr.groups.text,
                            'clean_progress': asr.frame_index == 0, 'ready_at': time.monotonic()}
            elif request['operation'] == 'step':
                if asr is None:
                    raise RuntimeError('No active X2 session')
                text, progress = [], []
                asr.on_text, asr.on_progress = text.append, progress.append
                engine.stage_records.clear()
                receipt = asr.step(WindowLedger(request), request['step_id'])
                receipt['stages'] = list(engine.stage_records)
                response = {'receipt': receipt, 'text': text, 'progress': progress, 'diagnostics': asr.diagnostics()}
            elif request['operation'] == 'clear':
                if asr is not None:
                    asr.cancel()
                    asr.on_text = asr.on_progress = None
                asr = None
                engine.past = engine.audio_past = engine.padding = engine.groups = None
                engine.stage_records.clear()
                engine.memory_samples.clear()
                torch.cuda.synchronize()
                response = {'kv_cleared': True, 'text_cleared': True, 'callbacks_cleared': True,
                            'counters_cleared': True, 'completed_at': time.monotonic()}
            else:
                raise ValueError('Unsupported X2 operation')
            send(connection, response)
        except Exception:
            send(connection, {'error': traceback.format_exc()})
            return


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fd', type=int, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    serve(parser.parse_args())
