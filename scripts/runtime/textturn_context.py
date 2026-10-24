"""Bounded shared transcripts and real-decoder-step windows for shadow control."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import threading
import time


class SharedContext:
    """Own versioned user turns and a bounded, cursor-addressable update log."""

    def __init__(self, max_updates=4096, max_turns=128):
        if max_updates < 1 or max_turns < 1:
            raise ValueError('Context bounds must be positive')
        self.latest = {}
        self.updates = deque(maxlen=max_updates)
        self.max_turns = max_turns
        self.sequence = 0
        self.lock = threading.RLock()

    def publish_user_transcript(self, snapshot):
        value = deepcopy(snapshot)
        required = {'session_id', 'turn_id', 'source', 'asr_generation', 'version',
                    'asr_prefix_version', 'text', 'status', 'received_at'}
        if not required <= value.keys() or value['source'] != 'nemotron':
            raise ValueError('Incomplete or unsupported transcript source')
        if value['status'] not in ('open', 'closed') or not isinstance(value['text'], str):
            raise ValueError('Invalid transcript lifecycle or text')
        if type(value['version']) is not int or value['version'] < 0:
            raise ValueError('Invalid transcript version')
        key = value['session_id'], value['turn_id']
        with self.lock:
            old = self.latest.get(key)
            if old is None:
                if len(self.latest) >= self.max_turns:
                    raise RuntimeError('Context turn bound exceeded')
                if value['version'] != 0 or value['status'] != 'open' or value['text']:
                    raise ValueError('A new turn must explicitly open with empty version zero')
            elif value['version'] < old['version']:
                return {'status': 'ignored_old_version', 'event_seq': old['event_seq']}
            elif value['version'] == old['version']:
                if any(value.get(k) != old.get(k) for k in ('text', 'status', 'asr_generation', 'asr_prefix_version')):
                    raise ValueError('Conflicting duplicate transcript version')
                return {'status': 'duplicate', 'event_seq': old['event_seq']}
            else:
                if value['version'] != old['version'] + 1 or old['status'] == 'closed':
                    raise ValueError('Transcript version gap or update after close')
                if value['asr_generation'] != old['asr_generation'] or not value['text'].startswith(old['text']):
                    raise ValueError('ASR generation change or unsupported transcript rewrite')
                if value['asr_prefix_version'] < old['asr_prefix_version']:
                    raise ValueError('ASR prefix version regressed')
                if value['status'] == 'closed' and (value['text'] != old['text'] or not value.get('close_reason')):
                    raise ValueError('Close must preserve the last visible text and state a reason')
            self.sequence += 1
            value.update(event_seq=self.sequence, published_at=time.monotonic())
            self.latest[key] = value
            self.updates.append(value)
            return {'status': 'published', 'event_seq': self.sequence}

    def get_user_turn(self, session_id, turn_id):
        with self.lock:
            return deepcopy(self.latest[(session_id, turn_id)])

    def read_user_transcript_updates(self, session_id, after_event_seq=0):
        with self.lock:
            if (after_event_seq < 0 or after_event_seq > self.sequence or
                    self.updates and after_event_seq < self.updates[0]['event_seq'] - 1):
                raise ValueError('Context cursor gap: resynchronize from the latest turn snapshot')
            return {'updates': [deepcopy(v) for v in self.updates
                                if v['event_seq'] > after_event_seq and v['session_id'] == session_id],
                    'cursor': self.sequence}


class TranscriptConsumer:
    """Read each committed version once without owning or rewriting transcripts."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.cursor = 0
        self.turns = {}
        self.versions_read = deque(maxlen=4096)

    def consume(self, context):
        batch = context.read_user_transcript_updates(self.session_id, self.cursor)
        for update in batch['updates']:
            key = update['turn_id']
            old = self.turns.get(key)
            if old is not None and update['version'] != old['version'] + 1:
                raise RuntimeError('Consumer observed a missing or duplicate turn version')
            self.turns[key] = deepcopy(update)
            self.versions_read.append((key, update['version'], update['event_seq']))
        self.cursor = batch['cursor']
        return batch['updates']


class ControlWindowAssembler:
    """Close a control window after three genuine, contiguous decode completions."""

    def __init__(self):
        self.pending = []
        self.last_step = 0
        self.window_start_text = ''
        self.last_text = ''
        self.first_new_text_at = None

    def push_step(self, event):
        if event.get('kind') != 'decode_step' or event['step_seq'] != self.last_step + 1:
            raise ValueError('Expected the next genuine decoder completion')
        if not event['text'].startswith(self.last_text):
            raise ValueError('Decoder transcript rewrote a published prefix')
        if event['text'] != self.last_text and self.first_new_text_at is None:
            self.first_new_text_at = event.get('text_visible_at', event['published_at'])
        self.last_text, self.last_step = event['text'], event['step_seq']
        self.pending.append(deepcopy(event))
        return self.flush() if len(self.pending) == 3 else None

    def flush(self):
        if not self.pending:
            return None
        first, last = self.pending[0], self.pending[-1]
        ready = last['published_at']
        start = self.first_new_text_at if self.first_new_text_at is not None else first['published_at']
        delta = last['text'][len(self.window_start_text):]
        window = {'first_step_seq': first['step_seq'], 'last_step_seq': last['step_seq'],
                  'step_count': len(self.pending), 'nominal_start_ms': first['nominal_audio_start_ms'],
                  'nominal_end_ms': last['nominal_audio_end_ms'], 'text': last['text'],
                  'text_before_window': self.window_start_text, 'user_delta': delta,
                  'observation': delta if delta else '<|no-voice|>',
                  'asr_prefix_version': last['prefix_version'], 'input_ready_at': ready,
                  'first_input_visible_at': start, 'aggregation_wait_ms': max(0., ready - start) * 1000,
                  'partial_window': len(self.pending) < 3, 'merged_windows': 0}
        self.pending = []
        self.window_start_text = last['text']
        self.first_new_text_at = None
        return window


class LatestControlWorker:
    """Allow one running request and one replaceable, cumulatively merged snapshot."""

    def __init__(self, decide):
        self.decide = decide
        self.condition = threading.Condition()
        self.pending = None
        self.active = False
        self.closing = False
        self.results = deque()
        self.merged = 0
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def submit(self, window):
        value = deepcopy(window)
        with self.condition:
            if self.closing:
                raise RuntimeError('Control worker is closed')
            if self.pending is not None:
                old = self.pending
                if not value['text'].startswith(old['text']):
                    raise ValueError('Cannot merge a transcript rewrite')
                value.update(text_before_window=old['text_before_window'],
                             first_step_seq=old['first_step_seq'], nominal_start_ms=old['nominal_start_ms'],
                             first_input_visible_at=old['first_input_visible_at'],
                             input_ready_at=old['input_ready_at'],
                             step_count=old['step_count'] + value['step_count'],
                             merged_windows=old['merged_windows'] + 1)
                value['user_delta'] = value['text'][len(value['text_before_window']):]
                value['observation'] = value['user_delta'] or '<|no-voice|>'
                value['aggregation_wait_ms'] = max(
                    0., value['input_ready_at'] - value['first_input_visible_at']) * 1000
                self.merged += 1
            self.pending = value
            self.condition.notify_all()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.closing)
                if self.pending is None:
                    return
                window, self.pending, self.active = self.pending, None, True
            started = time.monotonic()
            result = {'window': window, 'started_at': started, 'action': None}
            try:
                result['action'] = self.decide(deepcopy(window))
            except Exception as exc:
                result['error'] = repr(exc)
            result['returned_at'] = time.monotonic()
            result['control_ms'] = (result['returned_at'] - window['input_ready_at']) * 1000
            result['queue_ms'] = (started - window['input_ready_at']) * 1000
            with self.condition:
                if len(self.results) >= 4096:
                    self.closing = True
                    self.pending = None
                    result['error'] = 'Control result bound exceeded'
                self.results.append(result)
                self.active = False
                self.condition.notify_all()

    def drain_results(self):
        with self.condition:
            values = list(self.results)
            self.results.clear()
            return values

    def close(self, timeout=30):
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        self.worker.join(timeout)
        if self.worker.is_alive():
            raise RuntimeError('Control worker did not drain within the close timeout')
        return self.drain_results()
