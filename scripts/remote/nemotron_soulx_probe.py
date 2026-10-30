"""Check native RNNT text and SoulX states on existing development audio."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from shared_context import FrontendConsumer, SharedContext
from nemotron_soulx_frontend import NemotronSoulXFrontend


def rpc(path, operation, **payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(30)
        connection.connect(str(path))
        connection.sendall(json.dumps({'operation': operation, **payload}).encode() + b'\n')
        response = json.loads(connection.makefile('rb').readline(4 * 1024 * 1024))
    if 'error' in response:
        raise RuntimeError(response['error'])
    return response


def run_case(model, audio, case_id, path, output):
    import numpy as np
    identity = rpc(path, 'create')['session_id']
    readers = [FrontendConsumer(case_id), FrontendConsumer(case_id)]
    context = SharedContext()
    observations, failures, audio_metrics = [], [], []
    file = (output / f'{case_id}.events.jsonl').open('x')
    lock = threading.RLock()
    def consume(shared):
        with lock:
            batches = [consumer.consume(shared) for consumer in readers]
            if batches[0] != batches[1]:
                raise AssertionError('Independent consumers disagree')
            for event in batches[0]:
                observations.append(event)
                file.write(json.dumps(event, ensure_ascii=False) + '\n')
            file.flush()
    frontend = NemotronSoulXFrontend(model, context, session_id=case_id, turn_id='user-1', on_commit=consume)
    stopped, polling_stop = threading.Event(), threading.Event()
    eof = threading.Event()
    incoming = queue.Queue(maxsize=10)
    def poll():
        cursor = 0
        try:
            while not polling_stop.is_set():
                batch = rpc(path, 'poll', session_id=identity, after=cursor)
                for event in batch['events']:
                    frontend.accept_asr_event(event)
                    cursor = event['event_seq']
                if batch['ended']:
                    eof.set()
                    return
                polling_stop.wait(.005)
        except Exception:
            failures.append(traceback.format_exc())
            stopped.set()
    polling = threading.Thread(target=poll, daemon=True)
    polling.start()
    started = time.monotonic()
    def feed():
        try:
            for start in range(0, len(audio), 1280):
                end = min(start + 1280, len(audio))
                if stopped.wait(max(0, started + end / 16000 - time.monotonic())):
                    return
                chunk = audio[start:end].copy()
                pcm = (np.clip(chunk, -1, 1) * 32767).astype('<i2').tobytes()
                rpc(path, 'push', session_id=identity, audio=base64.b64encode(pcm).decode())
                incoming.put_nowait((np.frombuffer(pcm, '<i2').astype(np.float32) / 32768, time.monotonic()))
            incoming.put((None, time.monotonic()), timeout=3)
        except Exception:
            failures.append(traceback.format_exc())
            stopped.set()
    feeding = threading.Thread(target=feed, daemon=True)
    feeding.start()
    try:
        import torch
        with torch.inference_mode():
            while True:
                if failures:
                    raise RuntimeError(failures[0])
                chunk, arrived = incoming.get(timeout=5)
                if chunk is None:
                    break
                waited = time.monotonic() - arrived
                if waited > .8:
                    raise RuntimeError('SoulX input queue exceeded 800ms')
                before = time.monotonic()
                frontend.feed_audio(chunk)
                audio_metrics.append({'queue_ms': waited * 1000, 'compute_ms': (time.monotonic() - before) * 1000})
        frontend.close_turn('audio_eof')
        online = context.get_user_turn(case_id, 'user-1')['transcript']['text']
        rpc(path, 'push', session_id=identity, eof=True)
        if not eof.wait(15):
            raise RuntimeError('RNNT EOF drain did not finish within 15s')
        if failures:
            raise RuntimeError(failures[0])
        states = [e for e in observations if e['kind'] == 'user_state']
        controls = [e for e in observations if e['kind'] == 'control_observation']
        for control in controls:
            end = control['consumed_source_observed_until']
            if end is not None and end > control['audio_observed_until']:
                raise AssertionError('SoulX consumed future-observation ASR text')
        texts = [e['text'] for e in observations if e['kind'] == 'user_transcript']
        if not all(b.startswith(a) for a, b in zip(texts, texts[1:])):
            raise AssertionError('Context transcript prefix rewrote')
        if any(consumer.turns['user-1']['text'] != online for consumer in readers):
            raise AssertionError('Consumers did not preserve the last online prefix')
        return {'case_id': case_id, 'passed': True, 'online_text': online, 'drained_text': frontend.native_text,
                'events': len(observations), 'states': dict(Counter(e['token'] for e in states)),
                'accepted_states': dict(Counter(e['token'] for e in states if e['accepted'])),
                'transcript_updates': len(texts) - 2, 'token_replays': frontend.replay_count,
                'pending_control_frames': sum(e['asr_status'] == 'pending' for e in controls),
                'source_versions_consumed': sorted({e['consumed_source_prefix_version'] for e in controls}),
                'max_queue_ms': max((e['queue_ms'] for e in audio_metrics), default=0),
                'audio_metrics': audio_metrics, 'duration_seconds': len(audio) / 16000,
                'elapsed_seconds': time.monotonic() - started}
    finally:
        stopped.set()
        feeding.join(5)
        polling_stop.set()
        polling.join(5)
        if feeding.is_alive() or polling.is_alive():
            raise RuntimeError('Frontend probe threads did not terminate')
        frontend.detach(aborted=not frontend.closed)
        rpc(path, 'close', session_id=identity)
        file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--check-source', type=Path, required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    import torch
    import soundfile as sf
    import soxr
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.35, 0)
    args.output.mkdir(exist_ok=False)
    result = {'passed': False, 'cases': [], 'sensevoice_loaded': False,
              'nemotron_revision': 'ebe59e5a817142986528bbbee5dba8db7b38ed50',
              'soulx_revision': '61701c4ab8193cc1ee2220d3848872ac6c720142',
              'scope': 'native Nemotron + SoulX integration probe; no downstream model or playback'}
    try:
        loader = args.check_source / 'scripts/remote/check_component.py'
        if hashlib.sha256(loader.read_bytes()).hexdigest() != 'da9602cf09f30e42cdd9b7f43fd81b7519255bf0eb0161bc4af0372efe0e1901':
            raise ValueError('Reusable SoulX loader digest differs')
        sys.path.insert(0, str(args.check_source / 'scripts/remote'))
        upstream = args.assets / 'upstream/frozen-20261028'
        sys.path.insert(0, str(upstream / 'soulx-duplug'))
        import model.asr
        class UnusedASR:
            def __init__(self, language='en'):
                self.language = language
            def recognize(self, *args, **kwargs):
                raise AssertionError('A second ASR was called')
        original = model.asr.SensevoiceASR
        model.asr.SensevoiceASR = UnusedASR
        from check_component import load_soulx
        try:
            controller, checks = load_soulx(args.assets, upstream, args.output)
        finally:
            model.asr.SensevoiceASR = original
        result['checkpoint_checks'] = checks
        with torch.inference_mode():
            # Before capture, warm native audio forwards with a recognizer that
            # never runs SenseVoice. Silence normally leaves its gate closed.
            for _ in range(3):
                try:
                    controller.process(np.zeros(2560, dtype=np.float32))
                except AssertionError:
                    controller.reset()
        paths = [('fleurs', args.assets.parent / 'interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav'),
                 ('english_example', args.assets / 'models/sensevoice-small/example/en.mp3')]
        manifest = []
        inputs = []
        for name, path in paths:
            audio, rate = sf.read(path, dtype='float32')
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if rate != 16000:
                audio = soxr.resample(audio, rate, 16000)
            gain = min(.05 / np.sqrt(np.mean(audio.astype(np.float64) ** 2)), .9 / np.max(np.abs(audio)))
            audio = (audio * gain).astype(np.float32)
            inputs.append((name, audio))
            manifest.append({'name': name, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                             'gain': float(gain), 'native_rate': rate, 'samples': len(audio)})
        inputs.extend([('fleurs_prefix', inputs[0][1][:51200]), ('silence', np.zeros(32000, dtype=np.float32))])
        (args.output / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        for case_id, audio in inputs:
            controller.reset()
            record = run_case(controller, audio, case_id, args.socket, args.output)
            result['cases'].append(record)
            (args.output / 'progress.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(record, ensure_ascii=False), flush=True)
        result['passed'] = True
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        result['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
