#!/usr/bin/env python3
"""Measure native TTS audio packets and simulated audible onset over loopback HTTP."""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import signal
import struct
import sys
import time
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer


def quantiles(values):
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if not values:
        return {"n": 0}
    def percentile(p):
        x = (len(values) - 1) * p
        lo, hi = math.floor(x), math.ceil(x)
        return values[lo] * (hi - x) + values[hi] * (x - lo) if hi != lo else values[lo]
    return {"n": len(values), "p50": percentile(.5), "p90": percentile(.9),
            "p95": percentile(.95), "max": values[-1]}


def analyze(pcm, chunks, rate):
    """Map sample onset to causal playback, including late-arriving blocks."""
    samples = array.array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    block = max(1, round(rate * .01))
    starts, ends, intervals = [], [], []
    sample_offset, play_end, stalls, stall_seconds = 0, 0., 0, 0.
    for chunk in chunks:
        start = max(play_end, chunk['arrival_seconds'])
        if starts and chunk['arrival_seconds'] > play_end + .001:
            stalls += 1
            stall_seconds += chunk['arrival_seconds'] - play_end
        starts.append(start)
        play_end = start + chunk['samples'] / rate
        ends.append(play_end)
        intervals.append((sample_offset, sample_offset + chunk['samples'], start))
        sample_offset += chunk['samples']
    rms = [math.sqrt(sum(x*x for x in samples[i:i+block]) / block) / 32768
           for i in range(0, len(samples)-block+1, block)]
    result = {}
    for db in (-50, -45, -40):
        threshold, onset = 10 ** (db / 20), None
        for i in range(len(rms)-2):
            if all(x >= threshold for x in rms[i:i+3]):
                onset = i * block
                break
        audible = None
        if onset is not None:
            for first, last, start in intervals:
                if first <= onset < last:
                    audible = start + (onset - first) / rate
                    break
        result[f'onset_db{abs(db)}_seconds'] = None if onset is None else onset / rate
        result[f'audible_db{abs(db)}_seconds'] = audible
    result.update(audio_seconds=len(samples)/rate, stalls=stalls, stall_seconds=stall_seconds,
                  first_packet_seconds=chunks[0]['arrival_seconds'] if chunks else None,
                  first_packet_samples=chunks[0]['samples'] if chunks else 0,
                  max_packet_gap_seconds=max((b['arrival_seconds']-a['arrival_seconds']
                                            for a,b in zip(chunks,chunks[1:])), default=0.))
    return result


class Backend:
    def __init__(self, args):
        self.args = args
        import torch
        self.torch = torch
        torch.set_num_threads(args.threads)
        torch.manual_seed(args.seed)
        if args.backend == 'pocket':
            from pocket_tts import TTSModel
            self.model = TTSModel.load_model(**({'config': args.model} if args.model else {}))
            self.voice = self.model.get_state_for_audio_prompt(args.voice or 'alba')
            self.rate = self.model.sample_rate
        elif args.backend == 'kokoro':
            from kokoro import KPipeline
            self.model = KPipeline(lang_code='a', device=args.device, repo_id='hexgrad/Kokoro-82M')
            self.rate = 24000
        elif args.backend == 'kyutai':
            from moshi.models.loaders import CheckpointInfo
            from moshi.models.tts import TTSModel
            self.model = TTSModel.from_checkpoint_info(
                CheckpointInfo.from_hf_repo(args.model or 'kyutai/tts-1.6b-en_fr'),
                n_q=32, temp=.6, device=args.device)
            self.voice = self.model.make_condition_attributes(
                [Path(args.voice) if args.voice and args.voice.endswith('.safetensors') else self.model.get_voice_path(args.voice or 'expresso/ex03-ex01_happy_001_channel1_334s.wav')],
                cfg_coef=2.)
            self.rate = self.model.mimi.sample_rate
        else:
            raise ValueError(args.backend)

    def synthesize(self, text, emit):
        with (self.torch.no_grad() if self.args.backend == 'pocket' else self.torch.inference_mode()):
            if self.args.backend == 'pocket':
                for pcm in self.model.generate_audio_stream(self.voice, text):
                    emit(pcm)
            elif self.args.backend == 'kokoro':
                for _, _, pcm in self.model(text, voice=self.args.voice or 'af_heart', speed=1.):
                    emit(pcm)
            else:
                # Use the official model callback so codec frames are delivered immediately.
                def on_frame(frame):
                    if (frame != -1).all():
                        emit(self.model.mimi.decode(frame[:, 1:, :])[0, 0])
                entries = self.model.prepare_script([text], padding_between=1)
                with self.model.mimi.streaming(1):
                    self.model.generate([entries], [self.voice], on_frame=on_frame)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(self.server.metadata).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        text = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['text']
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('X-Sample-Rate', str(self.server.backend.rate))
        self.send_header('Connection', 'close')
        self.end_headers()
        def emit(pcm):
            data = (pcm.detach().float().cpu().flatten().clamp(-1, 1) * 32767).to(
                self.server.backend.torch.int16).numpy().astype('<i2').tobytes()
            if data:
                self.wfile.write(struct.pack('<I', len(data)))
                self.wfile.write(data)
                self.wfile.flush()
        try:
            self.server.backend.synthesize(text, emit)
            self.wfile.write(struct.pack('<I', 0))
            self.wfile.flush()
        except Exception:
            import traceback
            traceback.print_exc()
        self.close_connection = True

    def log_message(self, *_):
        pass


def exact_read(response, length):
    pieces, remaining = [], length
    while remaining:
        piece = response.read(remaining)
        if not piece:
            raise EOFError(f'Stream ended with {remaining} bytes missing')
        pieces.append(piece)
        remaining -= len(piece)
    return b''.join(pieces)


async def receive_moss(args, text, started, pcm, chunks, state):
    import asyncio
    import uuid
    import websockets
    async with websockets.connect(args.moss_url, max_size=None, open_timeout=args.timeout) as ws:
        await ws.send(json.dumps({'type': 'start', 'session_id': str(uuid.uuid4()),
                                  'text': '', 'prompt_audio': args.reference}))
        first = json.loads(await ws.recv())
        if first.get('type') != 'started':
            raise RuntimeError(f'Expected started: {first}')
        state['rate'] = int(first['sample_rate'])
        if first.get('audio_codec', 'pcm_s16le') != 'pcm_s16le' or first.get('channels', 1) != 1:
            raise ValueError('MOSS must return mono PCM16')
        await ws.send(json.dumps({'type': 'push', 'text': text, 'is_final': False}))
        await ws.send(json.dumps({'type': 'push', 'text': '', 'is_final': True}))
        async for message in ws:
            if isinstance(message, bytes):
                if not message:
                    continue
                if len(message) % 2:
                    raise ValueError('Partial PCM sample')
                chunks.append({'arrival_seconds': time.perf_counter()-started, 'samples': len(message)//2})
                pcm.extend(message)
            else:
                event = json.loads(message)
                if event.get('type') == 'error':
                    raise RuntimeError(str(event))
                if event.get('type') == 'completed':
                    return
        raise EOFError('MOSS closed before completed')


def measure(args, item, phase, output):
    pcm, chunks, error = bytearray(), [], None
    rate = 0
    connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=args.timeout)
    started = time.perf_counter()
    # A process alarm bounds the entire request, including a stream of slow packets.
    def expired(*_):
        raise TimeoutError('Request wall deadline exceeded')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, args.timeout)
    try:
        if args.backend == 'moss':
            import asyncio
            state = {'rate': 48000}
            try:
                asyncio.run(asyncio.wait_for(receive_moss(args, item['text'], started, pcm, chunks, state), args.timeout))
            finally:
                rate = state['rate']
        else:
            connection.request('POST', '/synthesize', body=json.dumps({'text': item['text']}),
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f'HTTP {response.status}')
            rate = int(response.getheader('X-Sample-Rate'))
            while True:
                length, = struct.unpack('<I', exact_read(response, 4))
                if not length:
                    break
                if length % 2 or length > 48000 * 60 * 2:
                    raise ValueError(f'Invalid PCM packet size: {length}')
                data = exact_read(response, length)
                arrived = time.perf_counter() - started
                chunks.append({'arrival_seconds': arrived, 'samples': length // 2})
                pcm.extend(data)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    finally:
        elapsed = time.perf_counter() - started
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        connection.close()
    if not chunks and error is None:
        error = 'No audio packets'
    record = dict(item, phase=phase, error=error, sample_rate=rate,
                  wall_seconds=elapsed, chunks=chunks, transport='native MOSS WebSocket PCM16' if args.backend == 'moss' else 'loopback HTTP framed PCM16')
    if rate:
        record.update(analyze(pcm, chunks, rate))
        record['rtf'] = elapsed / record['audio_seconds'] if record['audio_seconds'] else None
        with wave.open(str(output / f'{phase}_{item["id"]}.wav'), 'wb') as wav:
            wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm)
    (output / f'{phase}_{item["id"]}.json').write_text(json.dumps(record, indent=2))
    return record


def summarize(output):
    rows = [json.loads(p.read_text()) for p in sorted(output.glob('measured_*.json'))]
    result = {'attempted': len(rows), 'successful': sum(r['error'] is None for r in rows),
              'errors': [{'id': r['id'], 'error': r['error']} for r in rows if r['error']]}
    metrics = ('first_packet_seconds', 'audible_db50_seconds', 'audible_db45_seconds',
               'audible_db40_seconds', 'rtf', 'audio_seconds', 'stall_seconds', 'stalls',
               'first_packet_samples', 'max_packet_gap_seconds')
    for group in ['all', 'clarification', 'confirmation', 'answer']:
        chosen = [r for r in rows if r['error'] is None and (group == 'all' or r['category'] == group)]
        result[group] = {m: quantiles([r.get(m) for r in chosen]) for m in metrics}
    (output / 'summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result['all'], indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=['serve', 'run', 'summary'])
    parser.add_argument('--backend', choices=['pocket', 'kokoro', 'kyutai', 'moss'], default='pocket')
    parser.add_argument('--port', type=int, default=18761)
    parser.add_argument('--moss-url', default='ws://127.0.0.1:18004/tts/ws')
    parser.add_argument('--reference', default='/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/audio/reference.wav')
    parser.add_argument('--model')
    parser.add_argument('--voice')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--timeout', type=float, default=180.)
    parser.add_argument('--texts', type=Path, default=Path('configs/tts_selection_texts.csv'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'serve':
        backend = Backend(args)
        server = HTTPServer(('127.0.0.1', args.port), Handler)
        server.backend = backend
        import importlib.metadata
        packages = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
        server.metadata = dict(backend=args.backend, sample_rate=backend.rate, args=vars(args) | {'texts': str(args.texts), 'output': str(args.output)},
                               packages=packages, python=sys.version, platform=platform.platform())
        print(json.dumps(server.metadata), flush=True)
        server.serve_forever()
    elif args.command == 'summary':
        summarize(args.output)
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        with args.texts.open() as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 60 and len({r['id'] for r in rows}) == 60
        (args.output / 'client_config.json').write_text(json.dumps({k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()}, indent=2))
        (args.output / 'corpus_sha256.txt').write_text(hashlib.sha256(args.texts.read_bytes()).hexdigest())
        connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=10)
        connection.request('GET', '/health')
        (args.output / 'environment.json').write_bytes(connection.getresponse().read())
        connection.close()
        for phase, items in [('cold', rows[:1]), ('warmup', rows[:3]), ('measured', rows)]:
            for item in items:
                record = measure(args, item, phase, args.output)
                print(phase, item['id'], record.get('first_packet_seconds'), record['error'], flush=True)
                if record['error']:
                    summarize(args.output)
                    raise SystemExit(1)
        summarize(args.output)


if __name__ == '__main__':
    main()
