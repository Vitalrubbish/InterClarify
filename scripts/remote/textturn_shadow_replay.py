"""Replay frozen synthetic speech through real Nemotron and shared-context shadow control."""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
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
from score_textturn import metric


def normalize(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


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
    assembler = ControlWindowAssembler()
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
                trace.write(json.dumps({'kind': kind, **value}, ensure_ascii=False) + '\n')

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
    completed_reference_at = next((event['published_at'] for event in transcripts
                                  if normalize(event['text']).startswith(normalize(case['reference_text']))), None)
    trigger_at = next((event['published_at'] for event in transcripts
                       if re.search(r'\b(?:stop|pause|wait)\b', event['text'], re.I)), None)
    category = case['category']
    correct_action = 'stop' if category == 'interruption' else 'start'
    anchor = trigger_at if category == 'interruption' else completed_reference_at
    applicable = [r for r in actions if r.get('action') == correct_action]
    false_early = any(anchor is None or r['started_at'] < anchor for r in applicable)
    timely = anchor is not None and any(anchor <= r['returned_at'] <= anchor + 1. for r in applicable)
    quality_success = not false_early and timely and not any(r.get('error') for r in actions)
    pause_results = None
    if category == 'smooth_question_pause':
        prefix = normalize(case['pause_prefix_text'])
        pause_begin = next((event['published_at'] for event in transcripts
                            if normalize(event['text']) == prefix), None)
        resume = next((event['published_at'] for event in transcripts
                       if pause_begin is not None and event['published_at'] > pause_begin and
                       normalize(event['text']).startswith(prefix + ' ')), started + len(audio) / rate)
        observed = [r for r in actions if pause_begin is not None and pause_begin <= r['started_at'] < resume]
        pause_results = {'observable': bool(observed), 'false_start': any(r['action'] == 'start' for r in observed),
                         'success': bool(observed) and all(r['action'] == 'keep' for r in observed)}
    if category == 'backchannel':
        quality_success = completed_reference_at is not None and bool(actions) and all(
            r.get('action') != 'stop' and not r.get('error') for r in actions)
    return {'case_id': case['case_id'], 'source_id': case['source_id'], 'category': category,
            'success': quality_success, 'false_early_action': false_early if category != 'backchannel' else None,
            'anchor_at': anchor, 'pause': pause_results, 'context_ok': context_ok,
            'context_versions': len(consumer.versions_read), 'online_steps': len(steps),
            'online_transcripts': len(transcripts), 'eof_drain_events': len(offline),
            'asr_reference_complete': completed_reference_at is not None,
            'merged_windows': worker.merged, 'planned_windows': math_ceil(len(steps) / 3),
            'control_calls': len(actions), 'control_ms': [r['control_ms'] for r in actions],
            'aggregation_wait_ms': [r['window']['aggregation_wait_ms'] for r in actions],
            'elapsed_seconds': time.monotonic() - started,
            'runtime_success': bool(steps) and bool(actions) and not any(r.get('error') for r in actions)}


def math_ceil(value):
    import math
    return math.ceil(value)


def summarize(cases, results):
    lookup = {r['case_id']: r for r in results}
    rows = [lookup.get(c['case_id'], {'case_id': c['case_id'], 'category': c['category'],
                                    'source_id': c['source_id'], 'success': False, 'runtime_success': False}) for c in cases]
    metrics = {}
    for name, categories, negative in [
        ('smooth', ('smooth_question_pause', 'smooth_declarative'), False),
        ('declarative', ('smooth_declarative',), False), ('interruption', ('interruption',), False),
        ('backchannel_false_stop', ('backchannel',), True)]:
        selected = [r for r in rows if r['category'] in categories]
        metrics[name] = metric(sum(not r['success'] if negative else r['success'] for r in selected), len(selected))
    pauses = [r for r in rows if r['category'] == 'smooth_question_pause']
    metrics['pause_false_start'] = metric(sum(not (r.get('pause') or {}).get('success', False) for r in pauses), len(pauses))
    metrics['runtime'] = metric(sum(r['runtime_success'] for r in rows), len(rows))
    metrics['context'] = metric(sum(r.get('context_ok', False) for r in rows), len(rows))
    durations = sorted(ms for r in rows for ms in r.get('control_ms', []))
    metrics['control_ms_p95'] = durations[math_ceil(len(durations) * .95) - 1] if durations else None
    metrics['merged_windows'] = sum(r.get('merged_windows', 0) for r in rows)
    metrics['planned_windows'] = sum(r.get('planned_windows', 0) for r in rows)
    metrics['source_groups'] = len({c['source_id'] for c in cases})
    metrics['input_type'] = 'real_time_kokoro_synthetic_speech_to_native_nemotron'
    enough = metrics['source_groups'] >= 100
    quality = all(metrics[name]['rate'] is not None and metrics[name]['rate'] >= .8
                  for name in ('smooth', 'declarative', 'interruption')) and all(
        metrics[name]['rate'] is not None and metrics[name]['rate'] <= .15
        for name in ('pause_false_start', 'backchannel_false_stop'))
    operational = metrics['runtime']['rate'] is not None and metrics['runtime']['rate'] >= .95 and metrics['context']['rate'] == 1.
    latency = metrics['control_ms_p95'] is not None and metrics['control_ms_p95'] <= 500
    metrics['conclusion'] = 'insufficient_evidence' if not enough else 'pass_initial_screen' if quality and operational and latency else 'not_passed'
    return metrics


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
                          'success': False, 'runtime_success': False, 'error': repr(exc)}
            results.append(result)
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
            stream.flush()
            (args.output / 'summary.json').write_text(json.dumps(summarize(cases, results), indent=2) + '\n')
            print(json.dumps({'event': 'shadow_replay', 'completed': index + 1, 'planned': len(cases),
                              'runtime_success': result['runtime_success']}), flush=True)
    return summarize(cases, results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--asr-url', default='http://127.0.0.1:18815')
    parser.add_argument('--controller-url', default='http://127.0.0.1:18816')
    parser.add_argument('--limit', type=int, default=0)
    print(json.dumps(main(parser.parse_args()), indent=2))
