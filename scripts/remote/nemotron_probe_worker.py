"""Serve one existing native RNNT session over a private local Unix socket."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import socket
import time
import traceback

from nemotron_asr_service import NativeNemotron, NemotronService, load_pcm16


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--warmup-audio', type=Path, required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.55, 0)
    engine = NativeNemotron(args.model)
    service = NemotronService(engine, timeout=30)
    service.warmup(load_pcm16(args.warmup_audio), timeout=120)
    args.output.write_text(json.dumps({'ready_at': time.monotonic(), 'engine': engine.info,
                                       'warmup': 'two isolated native sessions',
                                       'observation_bound': 'callback consumed_samples is a conservative read watermark'}) + '\n')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(args.socket))
        args.socket.chmod(0o600)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                reader = connection.makefile('rb')
                request = {}
                try:
                    line = reader.readline(1024 * 1024)
                    if not line.endswith(b'\n'):
                        raise ValueError('Incomplete or oversized local RPC')
                    request = json.loads(line)
                    operation = request['operation']
                    if operation == 'create':
                        identity = service.create()
                        service.get(identity).source.max_pending = 12800
                        response = {'session_id': identity}
                    elif operation == 'push':
                        session = service.get(request['session_id'])
                        session.source.append(base64.b64decode(request.get('audio', ''), validate=True),
                                              eof=request.get('eof', False))
                        response = session.snapshot()
                    elif operation == 'poll':
                        session = service.get(request['session_id'])
                        response = session.read_events(request['after'])
                    elif operation == 'close':
                        service.close(request['session_id'])
                        response = {'ok': True}
                    elif operation == 'shutdown':
                        response = {'ok': True}
                    else:
                        raise ValueError('Unknown local RPC')
                except Exception as exc:
                    response = {'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()}
                connection.sendall(json.dumps(response, allow_nan=False).encode() + b'\n')
                if request.get('operation') == 'shutdown':
                    break
    args.socket.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
