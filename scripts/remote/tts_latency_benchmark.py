"""Replay fixed text arrivals against the pinned MOSS WebSocket service."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import importlib.metadata
import os
import subprocess
import sys
import statistics
import struct
import time
import uuid
import wave
from pathlib import Path


SHORT_TEXTS = [
    'Yes, that works.', 'No, please try again.', 'You can start now.',
    'The meeting starts at nine.', 'Please save the updated file.',
    'Your next stop is on the left.', 'The total is forty two dollars.',
    'I found three matching entries.', 'The timer is set for five minutes.',
    'Please check the blue folder.', 'Would you like tea or coffee?',
    'Which account should I use?', 'Do you mean this Friday?',
    'Should I include the attachment?', 'Which Alex did you mean?',
    'Is that the home address?', 'Do you want a return ticket?',
    'Should I keep the original name?', 'Would you prefer the earlier train?',
    'How many copies do you need?', 'Please confirm the room number.',
    'The package arrives tomorrow.', 'I can move it to Monday.',
    'Your changes have been saved.', 'The nearest exit is behind you.',
    'Would you like a shorter route?', 'Which version should I open?',
    'Should I send it to both people?', 'Is the amount in euros?',
    'Do you mean before or after lunch?',
]
EDGE_TEXTS = ['Yes.', '7.25, 16, and 2048.', 'Dr. Nguyen will meet José in Zürich.',
              'Wait — is that correct? Yes; please continue.',
              'Before leaving the station, check your platform number, keep your ticket ready, '
              'and allow enough time to walk to the far end of the platform.']


def corpus():
    """Return non-FDB texts with an explicit, fixed arrival schedule."""
    rows = []
    for index, text in enumerate(SHORT_TEXTS + EDGE_TEXTS):
        words = text.split(' ')
        deltas = [' '.join(words[i:i + 3]) + (' ' if i + 3 < len(words) else '')
                  for i in range(0, len(words), 3)]
        rows.append({'id': f'text_{index:02d}', 'text': text,
                     'category': 'short' if index < 30 else 'edge',
                     'deltas': [{'at_ms': i * 100, 'text': delta} for i, delta in enumerate(deltas)]})
    return rows


class PlaybackEstimate:
    """Estimate headless immediate-consumption buffer without a sound device."""

    def __init__(self):
        self.end = None
        self.underruns = 0
        self.underrun_seconds = 0.0

    def push(self, arrived, duration):
        """Return available audio after admitting one received PCM packet."""
        if self.end is not None and arrived > self.end:
            self.underruns += 1
            self.underrun_seconds += arrived - self.end
        self.end = max(arrived, self.end if self.end is not None else arrived) + duration
        return self.end - arrived


def pcm_onset(pcm, rate, threshold=0.01):
    """Estimate the first audible 10 ms RMS window; return sample offset."""
    count = len(pcm) // 2
    samples = struct.unpack('<' + 'h' * count, pcm[:count * 2])
    window = max(1, rate // 100)
    for start in range(0, count, window):
        chunk = samples[start:start + window]
        if math.sqrt(sum((x / 32768.0) ** 2 for x in chunk) / len(chunk)) >= threshold:
            return start
    return None


def distribution(values):
    """Report nearest-rank p95 and keep absent observations explicit."""
    if not values:
        return {'n': 0, 'mean': None, 'p50': None, 'p95': None}
    values = sorted(values)
    return {'n': len(values), 'mean': statistics.mean(values),
            'p50': statistics.median(values), 'p95': values[math.ceil(.95 * len(values)) - 1]}


def summarize(rows):
    """Group modes independently, retaining every attempted response."""
    result = {}
    for mode in sorted({row['mode'] for row in rows}):
        group = [row for row in rows if row['mode'] == mode]
        failed = sum(row['error'] is not None for row in group)
        result[mode] = {'attempts': len(group), 'failures': failed,
                        'failure_ratio': failed / len(group),
                        'no_audio': sum(row['samples'] == 0 for row in group),
                        'no_audio_ratio': sum(row['samples'] == 0 for row in group) / len(group),
                        'first_packet_samples': distribution([r['first_packet_samples'] for r in group
                            if r['error'] is None and r['samples'] > 0]),
                        'silent_audio': sum(row['samples'] > 0 and row['onset_seconds'] is None for row in group),
                        'first_pcm_seconds': distribution([r['first_pcm_seconds'] for r in group
                            if r['error'] is None and r['first_pcm_seconds'] is not None]),
                        'audible_estimate_seconds': distribution([r['audible_estimate_seconds'] for r in group
                            if r['error'] is None and r['audible_estimate_seconds'] is not None]),
                        'audio_per_wall': distribution([r['audio_per_wall'] for r in group if r['error'] is None]),
                        'simulated_underruns': sum(r['simulated_underruns'] for r in group)}
    return result


def first_pcm_stages(events):
    """Partition same-process enqueue-to-PCM time, leaving unknown time explicit."""
    grouped = {}
    for row in events:
        if row.get('response_id'):
            grouped.setdefault((row['response_id'], row['clock_domain']), []).append(row)
    result = []
    for (response_id, clock), rows in grouped.items():
        rows.sort(key=lambda r: r['monotonic_ns'])
        puts = [r['monotonic_ns'] for r in rows if r['event'] == 'queue.put']
        pcm = [r['monotonic_ns'] for r in rows if r['event'] == 'pcm.enqueued' and r.get('samples', 0) > 0]
        if not puts or not pcm:
            continue
        start, end = puts[0], pcm[0]
        if end <= start:
            continue
        starts, intervals = {}, []
        for row in rows:
            event = row['event']
            phase = event.rsplit('.', 1)[0]
            if phase not in ('model.prefill', 'model.step', 'codec.decode', 'voice.prepare'):
                continue
            if event.endswith('.start'):
                starts[phase] = row['monotonic_ns']
            elif event.endswith('.end') and phase in starts:
                left, right = max(start, starts.pop(phase)), min(end, row['monotonic_ns'])
                if right > left:
                    intervals.append((left, right, phase))
        boundaries = sorted({start, end, *(x for a, b, _ in intervals for x in (a, b))})
        times = {'unattributed_wait_and_preparation': 0.0}
        for left, right in zip(boundaries, boundaries[1:]):
            active = [phase for a, b, phase in intervals if a <= left and right <= b]
            phase = active[0] if len(active) == 1 else ('overlapping_spans' if active else 'unattributed_wait_and_preparation')
            times[phase] = times.get(phase, 0.0) + (right - left) / 1e9
        total = (end - start) / 1e9
        result.append({'response_id': response_id, 'clock_domain': clock,
                       'service_enqueue_to_first_pcm_seconds': total,
                       'seconds': times, 'fractions': {k: v / total for k, v in times.items()}})
    return result


def analyze_server_trace(events):
    """Aggregate complete CPU spans only within one response and process clock."""
    pending, durations = {}, {}
    for row in events:
        event = row['event']
        key = (row.get('response_id'), row['clock_domain'], event.rsplit('.', 1)[0])
        if event.endswith('.start'):
            pending[key] = row['monotonic_ns']
        elif event.endswith('.end') and key in pending:
            durations.setdefault(key[-1], []).append((row['monotonic_ns'] - pending.pop(key)) / 1e9)
    names = {r['event'] for r in events}
    required = ['queue.put', 'queue.get', 'model.prefill.start', 'model.prefill.end',
                'audio_frame', 'codec.decode.start', 'codec.decode.end', 'pcm.enqueued',
                'socket_send', 'physical_playback', 'voice_cache_hit']
    return {'first_pcm_stages': first_pcm_stages(events),
            'cpu_span_seconds': {k: distribution(v) for k, v in durations.items()},
            'missing_events': [name for name in required if name not in names],
            'unclosed_spans': len(pending),
            'decision': 'Measurement only; select a bottleneck after matched remote A/B and listening.'}


async def run_case(args, item, mode, repeat, output):
    """Send fixed deltas while receiving PCM on the same service protocol."""
    import websockets

    rid = str(uuid.uuid4())
    events, packets = [], []
    rate = 48000
    error = None
    buffer = PlaybackEstimate()
    started = time.monotonic()
    timeline = lambda event, **kw: events.append({'event': event, 'seconds': time.monotonic() - started,
        'request_id': rid, 'response_id': rid, 'clock_domain': 'client', **kw})
    timeline('text.available')
    try:
        async with websockets.connect(args.url, max_size=None, open_timeout=args.timeout) as ws:
            await ws.send(json.dumps({'type': 'start', 'session_id': rid,
                                      'text': '', 'prompt_audio': args.reference}))
            message = json.loads(await asyncio.wait_for(ws.recv(), args.timeout))
            if message.get('type') != 'started':
                raise RuntimeError(f'Expected started: {message}')
            rate = int(message['sample_rate'])
            if rate <= 0 or message.get('channels', 1) != 1 or message.get('audio_codec', 'pcm_s16le') != 'pcm_s16le':
                raise ValueError('Expected positive-rate mono PCM16 audio')

            async def receive():
                async for message in ws:
                    if isinstance(message, bytes):
                        if not message:
                            continue
                        if len(message) % 2:
                            raise ValueError("Received an incomplete PCM16 sample")
                        now = time.monotonic() - started
                        packets.append((now, message))
                        timeline('pcm.receive', samples=len(message) // 2,
                                 buffered_seconds=buffer.push(now, len(message) / (rate * 2)))
                    else:
                        event = json.loads(message)
                        timeline('server.control', control=event)
                        if event.get('type') == 'error':
                            raise RuntimeError(str(event))
                        if event.get('type') == 'completed':
                            return
                raise RuntimeError('Socket closed before completed')

            async def send():
                schedule = item['deltas'] if mode == 'incremental' else [{'at_ms': 0, 'text': item['text']}]
                origin = time.monotonic()
                for delta in schedule:
                    await asyncio.sleep(max(0, origin + delta['at_ms'] / 1000 - time.monotonic()))
                    timeline('text.push', text=delta['text'])
                    await ws.send(json.dumps({'type': 'push', 'text': delta['text'], 'is_final': False}))
                timeline('text.end')
                await ws.send(json.dumps({'type': 'push', 'text': '', 'is_final': True}))

            tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), args.timeout)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        timeline('failure', error=error)
    pcm = b''.join(p for _, p in packets)
    onset = pcm_onset(pcm, rate)
    consumed = 0
    audible = None
    # A detected waveform onset may occur in a later packet after an underrun.
    simulated_end = None
    for arrived, packet in packets:
        play_at = max(arrived, simulated_end if simulated_end is not None else arrived)
        if onset is not None and consumed <= onset < consumed + len(packet) // 2:
            audible = play_at + (onset - consumed) / rate
        consumed += len(packet) // 2
        simulated_end = play_at + len(packet) / (2 * rate)
    elapsed = time.monotonic() - started
    row = {'id': item['id'], 'mode': mode, 'repeat': repeat, 'response_id': rid,
           'error': error, 'samples': len(pcm) // 2, 'sample_rate': rate,
           'first_pcm_seconds': packets[0][0] if packets else None,
           'onset_seconds': onset / rate if onset is not None else None,
           'audible_estimate_seconds': audible, 'wall_seconds': elapsed,
           'audio_per_wall': len(pcm) / (2 * rate * max(elapsed, 1e-9)),
           'first_packet_samples': len(packets[0][1]) // 2 if packets else 0,
           'simulated_underruns': buffer.underruns,
           'simulated_underrun_seconds': buffer.underrun_seconds}
    stem = f'{item["id"]}_{mode}_{repeat}'
    with wave.open(str(output / (stem + '.wav')), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    (output / (stem + '.json')).write_text(json.dumps({'result': row, 'events': events}, indent=2))
    return row


def manifest():
    """Capture the checkout, adapter inputs and host without guessing revisions."""
    def command(argv):
        result = subprocess.run(argv, capture_output=True, text=True)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()}
    roots = {"interclarify": str(Path(__file__).resolve().parents[2])}
    roots.update({name: os.environ[name] for name in
                  ("XTALK_MOSS_SOURCE_ROOT", "XTALK_MOSS_SERVICE_ROOT", "XTALK_ROUND1_ROOT")
                  if os.environ.get(name)})
    versions = {}
    for name in ("torch", "transformers", "websockets", "flash-attn"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": sys.version, "conda_prefix": os.environ.get("CONDA_PREFIX"),
            "dependencies": versions,
            "sources": {name: {"path": root, "commit": command(["git", "-C", root, "rev-parse", "HEAD"]),
                                 "status": command(["git", "-C", root, "status", "--porcelain"])}
                        for name, root in roots.items()},
            "experiment_environment": {k: v for k, v in os.environ.items() if k.startswith("XTALK_TTS_")},
            "patch_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                             for name in ("moss_tts_patch.py", "moss_tts_service_patch.py", "tts_latency_trace.py")}}


async def run(args):
    """Run warmup separately and alternate the two fixed input modes."""
    items = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
    if not args.probe and (len(items) < 30 or args.repeats < 3):
        raise ValueError('Use at least 30 texts and 3 measured repeats')
    ids = [item['id'] for item in items]
    if len(ids) != len(set(ids)) or any(not value.replace('_', '').replace('-', '').isalnum() for value in ids):
        raise ValueError('Corpus IDs must be unique filename-safe identifiers')
    for item in items:
        if ''.join(d['text'] for d in item['deltas']) != item['text']:
            raise ValueError('Delta text must reconstruct the whole sentence exactly')
        times = [d['at_ms'] for d in item['deltas']]
        if not times or min(times) < 0 or times != sorted(times):
            raise ValueError('Arrival times must be nonnegative and ordered')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'config.json').write_text(json.dumps({**{k: str(v) for k, v in vars(args).items()},
        'corpus_sha256': hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        'playback': 'headless immediate consumption estimate; not speaker measurement',
        'manifest': manifest()}, indent=2))
    if args.probe:
        rows = [await run_case(args, items[0], mode, 'probe', args.output)
                for mode in ('whole', 'incremental')]
        (args.output / 'summary.json').write_text(json.dumps({'kind': 'probe', 'modes': summarize(rows)}, indent=2))
        return 1 if any(r['error'] or not r['samples'] for r in rows) else 0
    warm = await run_case(args, items[-1], 'whole', 'warmup', args.output)
    rows = []
    for repeat in range(args.repeats):
        for item in items:
            modes = ('whole', 'incremental') if repeat % 2 == 0 else ('incremental', 'whole')
            for mode in modes:
                row = await run_case(args, item, mode, repeat, args.output)
                rows.append(row)
                with (args.output / 'responses.jsonl').open('a') as handle:
                    handle.write(json.dumps(row) + '\n')
    report = {'warmup': warm, 'modes': summarize(rows), 'physical_playback': None,
              'quality_listening': 'pending', 'fdb_integration': 'pending'}
    if args.server_trace:
        report['server'] = analyze_server_trace([json.loads(line) for line in args.server_trace.read_text().splitlines()])
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2))
    return 1 if warm['error'] or any(r['error'] or not r['samples'] for r in rows) else 0


def main():
    """Prepare the text fixture or run against an already started service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-corpus', type=Path)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reference')
    parser.add_argument('--url', default='ws://127.0.0.1:8004/tts/ws')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--server-trace', type=Path)
    parser.add_argument('--probe', action='store_true', help='Run only the first text in both modes; not a performance matrix')
    args = parser.parse_args()
    if args.prepare_corpus:
        with args.prepare_corpus.open('x') as handle:
            handle.write(''.join(json.dumps(row) + '\n' for row in corpus()))
        return 0
    if not args.corpus or not args.output or not args.reference:
        parser.error('--corpus, --output and --reference are required')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
