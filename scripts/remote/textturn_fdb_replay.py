"""Replay frozen natural recordings through Nemotron and a simulated output lifecycle."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import threading
import time

import numpy as np
import requests
import soundfile as sf

from freeze_textturn_fdb import digest, write_json
from textturn_shadow_replay import (ControlTokenizer, ControlWindowAssembler, LatestControlWorker,
                                    ShadowState, SharedContext, TranscriptConsumer)


def load_audio(case, manifest):
    """Verify original assets and append the frozen arm-specific tail exactly once."""
    root = Path(manifest['root'])
    for value in case['files'].values():
        if digest(root / value['path']) != value['sha256']:
            raise ValueError('Frozen input changed')
    audio, rate = sf.read(root / case['files']['input.wav']['path'], dtype='float32')
    audio = (np.clip(audio, -1, 1) * 32767).astype('<i2')
    # Tail construction has one owner; the sender consumes this array unchanged.
    audio = np.concatenate((audio, np.zeros(int(case['tail_seconds'] * rate), dtype='<i2')))
    return audio, rate


def replay(case, manifest, args, tokenizer):
    protocol = manifest['protocol']
    audio, rate = load_audio(case, manifest)
    state = ShadowState({'category': 'turn_taking', 'assistant_text': protocol['assistant_text'],
                         'history': protocol['history'], 'source_id': '1'}, tokenizer,
                        control_ms=protocol['control_ms'], generation_ms=protocol.get('assistant_generation_ms', 480))
    state.tail_seconds = protocol.get('playback_tail_ms', protocol['playback_tail_windows'] * 480) / 1000
    shared, assembler = SharedContext(), ControlWindowAssembler(protocol['control_ms'])
    consumer = TranscriptConsumer(case['case_id'])
    transport = requests.Session()
    generation = None
    worker = sender = None
    sender_errors, timings, details = [], {}, {}
    version, cursor, steps, controls, drained = 0, 0, 0, 0, 0
    started = time.monotonic()
    path = args.output / 'traces' / (case['case_id'] + '.jsonl')
    with path.open('x') as trace:
        def record(kind, value):
            trace.write(json.dumps({**value, 'kind': kind}, ensure_ascii=False) + '\n')
            trace.flush()

        record('case_start', {'case_id': case['case_id'], 'started_at': started,
            'control_ms': protocol['control_ms'], 'assistant_generation_ms': protocol.get('assistant_generation_ms', 480),
            'original_seconds': case['duration_seconds'], 'sent_seconds': case['sent_seconds'],
            'tail_seconds': case['tail_seconds']})
        failure = None
        try:
            response = transport.post(args.asr_url + '/v1/session', timeout=10)
            response.raise_for_status()
            generation = response.json()['session_id']
            base = {'session_id': case['case_id'], 'turn_id': case['case_id'] + ':turn',
                    'source': 'nemotron', 'asr_generation': generation, 'status': 'open'}
            shared.publish_user_transcript({**base, 'version': 0, 'asr_prefix_version': 0,
                                             'text': '', 'received_at': time.monotonic()})
            consumer.consume(shared)
            text_times = {0: time.monotonic()}

            def decide(window):
                visible = state.snapshot(window)
                response = requests.post(args.controller_url + '/decide', json=visible, timeout=10)
                returned_at = time.monotonic()
                response.raise_for_status()
                service = response.json()
                if service['candidate_sha256'] != protocol['candidate_sha256']:
                    raise ValueError('Controller candidate changed')
                action = service['action']
                if action not in ({'keep', 'start'} if visible['state'] == 'Listen' else {'keep', 'stop'}):
                    raise ValueError('Illegal action')
                state.apply(action, visible, window['text'])
                with state.lock:
                    details[window['last_step_seq']] = {'visible': visible, 'service': service,
                        'action_returned_at': returned_at, 'state_after': state.state,
                        'state_recorded_at': time.monotonic()}
                return action

            def send():
                try:
                    with requests.Session() as http:
                        packet = int(rate * protocol['packet_ms'] / 1000)
                        for position in range(0, len(audio), packet):
                            time.sleep(max(0, timings['send_started_at'] + position / rate - time.monotonic()))
                            pcm = audio[position:position + packet].tobytes()
                            response = http.post(args.asr_url + '/v1/recognize', json={
                                'session_id': generation, 'audio': base64.b64encode(pcm).decode()}, timeout=10)
                            response.raise_for_status()
                            if position < case['frames'] <= position + packet:
                                timings['original_last_packet_at'] = time.monotonic()
                        time.sleep(max(0, timings['send_started_at'] + len(audio) / rate - time.monotonic()))
                        timings.update(input_end_at=time.monotonic(),
                            original_end_at=timings['send_started_at'] + case['duration_seconds'])
                        timings['eof_sent_at'] = time.monotonic()
                        response = http.post(args.asr_url + '/v1/recognize', json={
                            'session_id': generation, 'end_stream': True}, timeout=40)
                        response.raise_for_status()
                except Exception as exc:
                    sender_errors.append(repr(exc))

            worker = LatestControlWorker(decide)
            timings['send_started_at'] = time.monotonic()
            sender = threading.Thread(target=send, daemon=True)
            sender.start()

            def collect(values):
                nonlocal controls
                for value in values:
                    value.update(details.pop(value['window']['last_step_seq'], {}))
                    record('control_result', value)
                    controls += 1
                    if value.get('error'):
                        raise RuntimeError(value['error'])

            while time.monotonic() - started < len(audio) / rate + 65:
                response = transport.get(args.asr_url + f'/v1/session/{generation}/events',
                                         params={'after': cursor}, timeout=10)
                response.raise_for_status()
                batch = response.json()
                for event in batch['events']:
                    cursor = event['event_seq']
                    if event.get('eof_received'):
                        record('asr_eof_drain', {**event, 'asr_kind': event['kind']})
                        drained += 1
                        continue
                    record('asr_online', {**event, 'asr_kind': event['kind']})
                    if event['kind'] == 'transcript':
                        latest = shared.get_user_turn(base['session_id'], base['turn_id'])
                        if event['text'] == latest['text']:
                            continue
                        version += 1
                        shared.publish_user_transcript({**base, 'version': version,
                            'asr_prefix_version': event['prefix_version'], 'text': event['text'],
                            'received_at': time.monotonic(), 'asr_visible_at': event['published_at']})
                        latest = shared.get_user_turn(base['session_id'], base['turn_id'])
                        text_times[event['prefix_version']] = latest['published_at']
                        record('context_publish', latest)
                        for update in consumer.consume(shared):
                            record('context_read', {'version': update['version'], 'text': update['text'],
                                                   'read_at': time.monotonic()})
                    else:
                        latest = shared.get_user_turn(base['session_id'], base['turn_id'])
                        if latest['text'] != event['text'] or latest['asr_prefix_version'] != event['prefix_version']:
                            raise RuntimeError('Shared Context differs from decoder input')
                        event['text_visible_at'] = text_times[event['prefix_version']]
                        steps += 1
                        window = assembler.push_step(event)
                        if window:
                            record('control_window', window)
                            worker.submit(window)
                collect(worker.drain_results())
                if sender_errors:
                    raise RuntimeError(sender_errors[0])
                if batch['ended'] and not sender.is_alive():
                    break
                time.sleep(.01)
            else:
                raise TimeoutError('Replay deadline exceeded')
            residual = assembler.flush()
            if residual:
                record('eof_partial_window', residual)
            collect(worker.close())
            latest = shared.get_user_turn(base['session_id'], base['turn_id'])
            shared.publish_user_transcript({**latest, 'version': version + 1, 'status': 'closed',
                'close_reason': 'input_and_online_control_finished', 'received_at': time.monotonic()})
            consumer.consume(shared)
            if consumer.turns[base['turn_id']]['text'] != latest['text'] or not steps or not controls:
                raise RuntimeError('Missing control observations or Context mismatch')
        except Exception as exc:
            failure = repr(exc)
        finally:
            try:
                if worker:
                    for value in worker.close(timeout=15):
                        value.update(details.pop(value['window']['last_step_seq'], {}))
                        record('control_result', value)
                if sender:
                    sender.join(timeout=45)
                    if sender.is_alive():
                        raise RuntimeError('Sender still active; abort remaining run')
                if generation:
                    response = transport.delete(args.asr_url + f'/v1/session/{generation}', timeout=40)
                    response.raise_for_status()
            except Exception as exc:
                record('cleanup_failure', {'error': repr(exc)})
                raise
            finally:
                transport.close()
                record('input_timing', timings)
                for value in state.lifecycle:
                    record('simulated_lifecycle', value)
                record('case_end', {'runtime_success': failure is None, 'error': failure,
                    'steps': steps, 'control_calls': controls, 'merged_windows': worker.merged if worker else 0,
                    'eof_drain_events': drained, 'ended_at': time.monotonic()})
    return {'case_id': case['case_id'], 'runtime_success': failure is None, 'error': failure}


def main(args):
    manifest = json.loads(args.manifest.read_text())
    if not manifest['complete']:
        raise ValueError('Sampling incomplete; do not infer')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'traces').mkdir()
    tokenizer = ControlTokenizer(args.tokenizer)
    records = manifest['smoke'] if args.smoke else manifest['records']
    with (args.output / 'cases.jsonl').open('x') as stream:
        for index, case in enumerate(records):
            try:
                result = replay(case, manifest, args, tokenizer)
            except Exception as exc:
                result = {'case_id': case['case_id'], 'runtime_success': False, 'error': repr(exc)}
                stream.write(json.dumps(result) + '\n')
                stream.flush()
                # Failed cleanup must not leak concurrent sessions into another recording.
                raise
            stream.write(json.dumps(result) + '\n')
            stream.flush()
            write_json(args.output / 'progress.json', {'planned': len(records), 'completed': index + 1})
            if args.smoke and not result['runtime_success']:
                raise RuntimeError('Runtime smoke failed; preserve records and stop')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--asr-url', default='http://127.0.0.1:18815')
    parser.add_argument('--controller-url', default='http://127.0.0.1:18816')
    parser.add_argument('--smoke', action='store_true')
    main(parser.parse_args())
