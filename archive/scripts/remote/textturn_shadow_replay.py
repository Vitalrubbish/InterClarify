"""Replay frozen synthetic speech through real Nemotron and shared-context shadow control."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

import numpy as np
import requests
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from textturn_context import ControlWindowAssembler, LatestControlWorker, SharedContext, TranscriptConsumer
from build_textturn_dataset import ControlTokenizer, strip_terminal
from score_textturn_trace import run as rescore_traces



class ShadowState:
    """Simulate one output lifecycle; no real playback or external action ownership."""

    def __init__(self, case, tokenizer):
        self.lock = threading.RLock()
        self.state = 'Speak' if case['category'] in ('backchannel', 'interruption') else 'Listen'
        self.chunks = list(tokenizer.chunks(case['assistant_text'], 8, merge_terminal=False))
        self.history = case['history'].copy()
        self.generation_started = time.monotonic() - .48 if self.state == 'Speak' else None
        self.tail_seconds = .48 * (1 + int(case['source_id']) % 3)
        self.empty_streak = 0
        self.user_offset = 0
        self.lifecycle = []

    def snapshot(self, window):
        with self.lock:
            now = time.monotonic()
            count = 0 if self.generation_started is None else min(
                len(self.chunks), max(0, int((now - self.generation_started) / .48)))
            assistant = ''.join(self.chunks[:count]) if self.state == 'Speak' else ''
            complete = count == len(self.chunks) if self.state == 'Speak' else None
            if self.state == 'Speak' and complete and now >= self.generation_started + len(self.chunks) * .48 + self.tail_seconds:
                self.history.append({'role': 'assistant', 'text': assistant})
                self.state = 'Listen'
                self.lifecycle.append({'kind': 'playback_complete', 'at': now})
                assistant, complete = '', None
            observation = strip_terminal(window['user_delta']) or '<|no-voice|>'
            self.empty_streak = self.empty_streak + max(1, math_ceil(window['step_count'] / 3)) if observation == '<|no-voice|>' else 0
            return {'history': self.history.copy(), 'user_text': strip_terminal(window['text'][self.user_offset:]),
                    'assistant_visible': assistant, 'state': self.state, 'observation': observation,
                    'window_ms': window['nominal_end_ms'] - window['nominal_start_ms'],
                    'consecutive_no_voice_windows': self.empty_streak,
                    'assistant_generation_complete': complete, 'cot': ''}

    def apply(self, action, visible, text):
        with self.lock:
            now = time.monotonic()
            if action == 'start':
                self.history.append({'role': 'user', 'text': text[self.user_offset:]})
                self.user_offset = len(text)
                self.state, self.generation_started, self.empty_streak = 'Speak', now, 0
            elif action == 'stop':
                self.history.append({'role': 'assistant', 'text': visible['assistant_visible'],
                                     'interrupted': True, 'generated_only': True})
                self.state, self.generation_started, self.empty_streak = 'Listen', None, 0
            if action != 'keep':
                self.lifecycle.append({'kind': 'control_applied', 'action': action, 'at': now})


def replay_case(case, args, tokenizer):
    audio_path = args.audio / case['path']
    if hashlib.sha256(audio_path.read_bytes()).hexdigest() != case['sha256']:
        raise ValueError('Frozen audio changed')
    audio, rate = sf.read(audio_path, dtype='int16')
    if rate != 16000 or audio.ndim != 1:
        raise ValueError('Expected mono16k audio')
    # Leave an observed online response interval before the separately recorded EOF drain.
    audio = np.concatenate([audio, np.zeros(int(1.92 * rate), dtype=np.int16)])
    output = args.output / 'traces' / f"{case['case_id']}.jsonl"
    shared = SharedContext()
    consumer = TranscriptConsumer(case['case_id'])
    assembler = ControlWindowAssembler(480)
    state = ShadowState(case, tokenizer)
    session = requests.Session()
    response = session.post(args.asr_url + '/v1/session', timeout=10)
    response.raise_for_status()
    generation = response.json()['session_id']
    turn_id = case['case_id'] + ':turn'
    version = 0
    prefix_version = 0
    shared.publish_user_transcript({'session_id': case['case_id'], 'turn_id': turn_id, 'source': 'nemotron',
        'asr_generation': generation, 'version': 0, 'asr_prefix_version': 0, 'text': '', 'status': 'open',
        'received_at': time.monotonic(), 'audio_observed_until': 0})
    consumer.consume(shared)
    sender_errors, eof_started = [], threading.Event()
    started = time.monotonic()

    def send_audio():
        try:
            with requests.Session() as transport:
                for position in range(0, len(audio), 1280):
                    due = started + position / rate
                    remaining = due - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    pcm = audio[position:position + 1280].astype('<i2').tobytes()
                    sent = transport.post(args.asr_url + '/v1/recognize', json={
                        'session_id': generation, 'audio': base64.b64encode(pcm).decode()}, timeout=10)
                    sent.raise_for_status()
                eof_started.set()
                sent = transport.post(args.asr_url + '/v1/recognize', json={
                    'session_id': generation, 'end_stream': True}, timeout=40)
                sent.raise_for_status()
        except Exception as exc:
            sender_errors.append(repr(exc))

    request_details = {}

    def decide(window):
        visible = state.snapshot(window)
        response = requests.post(args.controller_url + '/decide', json=visible, timeout=10)
        response.raise_for_status()
        result = response.json()
        request_details[window['last_step_seq']] = {'visible': visible, 'service': result}
        state.apply(result['action'], visible, window['text'])
        return result['action']

    worker = LatestControlWorker(decide)
    sender = threading.Thread(target=send_audio, daemon=True)
    sender.start()
    cursor = 0
    actions, transcripts, steps, offline, context_events = [], [], [], [], []
    text_times = {0: started}
    try:
        with output.open('w') as trace:
            def record(kind, value):
                trace.write(json.dumps({**value, 'source_kind': value.get('kind'), 'kind': kind}, ensure_ascii=False) + '\n')

            while time.monotonic() - started < len(audio) / rate + 50:
                result = session.get(args.asr_url + f'/v1/session/{generation}/events',
                                     params={'after': cursor}, timeout=10)
                result.raise_for_status()
                batch = result.json()
                for event in batch['events']:
                    cursor = event['event_seq']
                    if event.get('eof_received'):
                        offline.append(event)
                        record('asr_eof_drain', event)
                        continue
                    record('asr_online', event)
                    if event['kind'] == 'transcript':
                        version += 1
                        prefix_version = event['prefix_version']
                        text_times[prefix_version] = event['published_at']
                        shared.publish_user_transcript({'session_id': case['case_id'], 'turn_id': turn_id,
                            'source': 'nemotron', 'asr_generation': generation, 'version': version,
                            'asr_prefix_version': prefix_version, 'text': event['text'], 'status': 'open',
                            'received_at': time.monotonic(), 'asr_visible_at': event['published_at'],
                            'audio_observed_until': event['consumed_samples']})
                        latest = shared.get_user_turn(case['case_id'], turn_id)
                        context_events.append(latest)
                        record('context_publish', latest)
                        updates = consumer.consume(shared)
                        for update in updates:
                            record('context_read', {'event_seq': update['event_seq'], 'version': update['version'],
                                                    'text': update['text'], 'read_at': time.monotonic()})
                        transcripts.append(event)
                    else:
                        event['text_visible_at'] = text_times[event['prefix_version']]
                        latest = shared.get_user_turn(case['case_id'], turn_id)
                        if latest['text'] != event['text'] or latest['asr_prefix_version'] != event['prefix_version']:
                            raise RuntimeError('Controller and Context observed different ASR versions')
                        steps.append(event)
                        window = assembler.push_step(event)
                        if window:
                            record('control_window', window)
                            worker.submit(window)
                for result in worker.drain_results():
                    result.update(request_details.pop(result['window']['last_step_seq'], {}))
                    actions.append(result)
                    record('control_result', result)
                trace.flush()
                if sender_errors:
                    raise RuntimeError(sender_errors[0])
                if batch['ended'] and not sender.is_alive():
                    break
                time.sleep(.01)
            else:
                raise RuntimeError('ASR replay deadline exceeded')
            tail = assembler.flush()
            if tail:
                record('control_window', tail)
                worker.submit(tail)
            for result in worker.close():
                result.update(request_details.pop(result['window']['last_step_seq'], {}))
                actions.append(result)
                record('control_result', result)
            latest = shared.get_user_turn(case['case_id'], turn_id)
            shared.publish_user_transcript({**latest, 'version': version + 1, 'status': 'closed',
                                            'close_reason': 'replay_audio_eof', 'received_at': time.monotonic()})
            record('context_close', shared.get_user_turn(case['case_id'], turn_id))
            for update in consumer.consume(shared):
                record('context_read', {'event_seq': update['event_seq'], 'version': update['version'],
                                        'text': update['text'], 'read_at': time.monotonic()})
            for event in state.lifecycle:
                record('simulated_lifecycle', event)
    finally:
        worker.close(timeout=15)
        sender.join(timeout=45)
        response = session.delete(args.asr_url + f'/v1/session/{generation}', timeout=40)
        response.raise_for_status()
        session.close()
    if sender.is_alive():
        raise RuntimeError('Audio sender did not terminate')
    latest = shared.get_user_turn(case['case_id'], turn_id)
    context_ok = consumer.turns[turn_id]['text'] == latest['text'] and len(consumer.versions_read) == version + 2
    return {'case_id': case['case_id'], 'source_id': case['source_id'], 'category': case['category'],
            'context_ok': context_ok, 'context_versions': len(consumer.versions_read),
            'online_steps': len(steps), 'online_transcripts': len(transcripts),
            'eof_drain_events': len(offline), 'merged_windows': worker.merged,
            'control_calls': len(actions), 'elapsed_seconds': time.monotonic() - started,
            'runtime_success': bool(steps) and bool(actions) and not any(r.get('error') for r in actions)}


def math_ceil(value):
    import math
    return math.ceil(value)


def main(args):
    manifest = json.loads((args.audio / 'manifest.json').read_text())
    if not manifest['complete']:
        raise ValueError('Audio preparation is incomplete')
    cases = manifest['records']
    if args.limit:
        sources = list(dict.fromkeys(c['source_id'] for c in cases))[:args.limit]
        cases = [c for c in cases if c['source_id'] in sources]
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Replay output must be fresh')
    args.output.mkdir(parents=True)
    (args.output / 'traces').mkdir()
    tokenizer = ControlTokenizer(args.tokenizer)
    results = []
    with (args.output / 'cases.jsonl').open('w') as stream:
        for index, case in enumerate(cases):
            try:
                result = replay_case(case, args, tokenizer)
            except Exception as exc:
                result = {'case_id': case['case_id'], 'source_id': case['source_id'], 'category': case['category'],
                          'runtime_success': False, 'error': repr(exc)}
            results.append(result)
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
            stream.flush()
            (args.output / 'progress.json').write_text(json.dumps(
                {'planned': len(cases), 'completed': index + 1,
                 'runtime_successful': sum(r['runtime_success'] for r in results)}, indent=2) + '\n')
            print(json.dumps({'event': 'shadow_replay', 'completed': index + 1, 'planned': len(cases),
                              'runtime_success': result['runtime_success']}), flush=True)
    planned_manifest = args.output / 'planned_manifest.json'
    planned_manifest.write_text(json.dumps({**manifest, 'records': cases}, ensure_ascii=False) + '\n')
    result = rescore_traces(argparse.Namespace(
        manifest=planned_manifest, traces=args.output / 'traces',
        annotations=getattr(args, 'annotations', None), output=args.output / 'score-v2'))
    (args.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--asr-url', default='http://127.0.0.1:18815')
    parser.add_argument('--controller-url', default='http://127.0.0.1:18816')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--annotations', type=Path)
    print(json.dumps(main(parser.parse_args()), indent=2))
