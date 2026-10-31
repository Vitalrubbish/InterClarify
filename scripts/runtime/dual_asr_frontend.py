"""Pair independent frozen state and RNNT completions using real PCM coverage."""
from collections import deque
from copy import deepcopy
import json
import threading
import time

try:
    from .soulx_frontend import SoulXFrontend
except ImportError:
    from soulx_frontend import SoulXFrontend


def record_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


class PairedPublisher:
    """Accept bounded observations; one consumer commits in main-block order."""

    def __init__(self, context, session_id, turn_id='user-1', on_commit=None,
                 max_states=8, max_steps=16, max_bytes=1048576):
        self.context, self.session_id, self.turn_id = context, session_id, turn_id
        self.on_commit = on_commit
        self.max_states, self.max_steps, self.max_bytes = max_states, max_steps, max_bytes
        self.states, self.steps = deque(), deque()
        self.state_bytes = self.step_bytes = 0
        self.state_end = self.step_seq = self.step_end = self.next_end = 0
        self.previous_text = ''
        self.lock, self.writer = threading.Lock(), threading.Lock()
        self.closed = False
        self.peaks = {'states': 0, 'steps': 0, 'state_bytes': 0, 'step_bytes': 0}

    def _append(self, queue, value, kind, limit):
        size = record_bytes(value)
        total = getattr(self, kind + '_bytes') + size
        if len(queue) >= limit or total > self.max_bytes:
            raise RuntimeError(f'Paired {kind} queue hard limit exceeded')
        queue.append((value, size))
        setattr(self, kind + '_bytes', total)
        self.peaks[kind + 's'] = max(self.peaks[kind + 's'], len(queue))
        self.peaks[kind + '_bytes'] = max(self.peaks[kind + '_bytes'], total)

    def submit_state(self, state):
        value = deepcopy(state)
        with self.lock:
            if self.closed:
                raise ValueError('Paired publisher is closed')
            end = value['processed_until']
            valid_end = 0 < end <= 2560 if not self.state_end else end == self.state_end + 2560
            if not valid_end or value['audio_observed_until'] < end:
                raise ValueError('Unordered or invalid SoulX real audio coverage')
            oldest = self.states[0][0] if self.states else value
            main_spans = oldest.get('soulx_audio_spans', {}).get('main', [])
            begin = min((s['start'] for s in main_spans if s['kind'] == 'real'),
                        default=max(0, oldest['processed_until'] - 2560))
            if end - begin > 12800:
                raise RuntimeError('Pending state audio span exceeded 800ms')
            self._append(self.states, value, 'state', self.max_states)
            self.state_end = end

    def submit_step(self, step):
        value = deepcopy(step)
        with self.lock:
            if self.closed:
                raise ValueError('Paired publisher is closed')
            end = value['feature_end_sample']
            if (value['step_seq'] != self.step_seq + 1 or end <= self.step_end
                    or (self.next_end and end != self.next_end)
                    or value['feature_start_sample'] < 0
                    or value['consumed_samples'] != end or end > value['received_samples']
                    or value['next_feature_end_sample'] <= end
                    or value['decode_completed_at'] < value['decode_started_at']):
                raise ValueError('Invalid native decoder completion coverage or order')
            if not isinstance(value['text'], str) or len(value['text']) > 65536:
                raise RuntimeError('Native transcript character limit exceeded')
            self._append(self.steps, value, 'step', self.max_steps)
            self.step_seq, self.step_end = value['step_seq'], end
            self.next_end = value['next_feature_end_sample']

    def publish_ready(self):
        if not self.writer.acquire(blocking=False):
            raise RuntimeError('Only one paired Context writer is allowed')
        published = []
        try:
            while True:
                with self.lock:
                    if self.closed or not self.states:
                        break
                    state = self.states[0][0]
                    required = max(state['processed_until'], state['audio_observed_until'])
                    while self.steps and self.steps[0][0]['feature_end_sample'] < required:
                        _, size = self.steps.popleft()
                        self.step_bytes -= size
                    if not self.steps:
                        break
                    step = deepcopy(self.steps[0][0])
                    state, size = self.states.popleft()
                    self.state_bytes -= size
                now = time.monotonic()
                frame = {**state, 'source': 'nemotron', 'text': step['text'],
                         'assembly_status': 'native', 'coverage_complete': True,
                         'soulx_audio_observed_until': state['audio_observed_until'],
                         'audio_observed_until': max(required, step['feature_end_sample']),
                         'native_step': step, 'pairing_mode': 'audio_coverage',
                         'pair_ready_at': now,
                         'publication_wait_ms': (now - state['state_resolved_at']) * 1000,
                         'pair_wait_after_controller_ms': (now - state['controller_completed_at']) * 1000,
                         'raw_delta_text': step['text'][len(self.previous_text):]
                         if step['text'].startswith(self.previous_text) else None}
                snapshot = self.context.publish_user_frame(frame)
                self.previous_text = step['text']
                published.append(snapshot)
                if self.on_commit:
                    self.on_commit(snapshot)
            return published
        finally:
            self.writer.release()

    def diagnostics(self):
        with self.lock:
            return {'unpublished_states': [deepcopy(v) for v, _ in self.states],
                    'unmatched_steps': [deepcopy(v) for v, _ in self.steps],
                    'state_bytes': self.state_bytes, 'step_bytes': self.step_bytes,
                    'queue_peaks': dict(self.peaks)}

    def close(self, reason='runtime_audio_case_end'):
        with self.writer:
            with self.lock:
                self.closed = True
                self.states.clear()
                self.steps.clear()
                self.state_bytes = self.step_bytes = 0
            return self.context.close_user_turn(self.session_id, self.turn_id, reason)


class DualASRFrontend(SoulXFrontend):
    """Run the frozen SenseVoice controller while deferring public text/state."""

    def __init__(self, model, publisher, **kwargs):
        super().__init__(model, publisher.context, publisher.session_id, publisher.turn_id,
                         frame_sink=publisher.submit_state, publication_source='nemotron', **kwargs)
