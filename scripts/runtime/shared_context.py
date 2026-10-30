"""Atomically replace each user turn's current transcript and audio state."""
from __future__ import annotations

from copy import deepcopy
import json
import threading
import time


STATE_IDS = {'<|user_idle|>': 151680, '<|user_nonidle|>': 151681,
             '<|user_backchannel|>': 151677, '<|user_complete|>': 151676,
             '<|user_incomplete|>': 151678}


class SharedContext:
    """Keep one bounded current observation per logical user turn, without history."""

    def __init__(self, max_turns=128, max_chars=65536, max_snapshot_bytes=256 * 1024):
        if any(type(value) is not int or value < 1
               for value in (max_turns, max_chars, max_snapshot_bytes)):
            raise ValueError('Context limits must be positive integers')
        self.max_turns, self.max_chars = max_turns, max_chars
        self.max_snapshot_bytes = max_snapshot_bytes
        self.latest = {}
        self.changed = threading.Condition(threading.RLock())

    @staticmethod
    def _key(session_id, turn_id):
        if any(not isinstance(value, str) or not value for value in (session_id, turn_id)):
            raise ValueError('Session and turn identifiers must be nonempty strings')
        return session_id, turn_id

    def _store(self, key, value):
        if len(value['text']) > self.max_chars:
            raise RuntimeError('Context transcript character limit exceeded')
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
        if size > self.max_snapshot_bytes:
            raise RuntimeError('Context snapshot byte limit exceeded')
        self.latest[key] = value
        self.changed.notify_all()
        return deepcopy(value)

    def open_user_turn(self, session_id, turn_id):
        """Open one empty SenseVoice turn; reuse requires explicit closed-turn release."""
        key = self._key(session_id, turn_id)
        with self.changed:
            if key in self.latest:
                raise ValueError('User turn already exists')
            if len(self.latest) >= self.max_turns:
                raise RuntimeError('Context turn limit exceeded')
            value = {'session_id': session_id, 'turn_id': turn_id, 'source': 'sensevoice_small',
                     'text': '', 'state_token': None, 'state_token_id': None,
                     'state_accepted': False, 'rejection_reason': 'initializing',
                     'processed_until': 0, 'audio_observed_until': 0,
                     'assembly_status': 'empty', 'coverage_complete': False,
                     'status': 'open', 'published_at': time.monotonic()}
            return self._store(key, value)

    def publish_user_frame(self, frame):
        """Publish a complete processed-audio observation, including text corrections."""
        value = deepcopy(frame)
        required = {'session_id', 'turn_id', 'source', 'text', 'state_token', 'state_token_id',
                    'state_accepted', 'processed_until', 'audio_observed_until',
                    'coverage_complete', 'assembly_status', 'status'}
        if not required <= value.keys():
            raise ValueError('Incomplete user frame')
        if {'version', 'asr_version', 'replace_from', 'replacement', 'event_seq'} & value.keys():
            raise ValueError('User frames contain current values, not transcript revisions')
        key = self._key(value['session_id'], value['turn_id'])
        if value['source'] != 'sensevoice_small' or value['status'] != 'open':
            raise ValueError('Unsupported user frame source or lifecycle')
        if not isinstance(value['text'], str):
            raise ValueError('Transcript must be a string')
        if type(value['state_accepted']) is not bool or type(value['coverage_complete']) is not bool:
            raise ValueError('Invalid user frame flags')
        if value['state_accepted'] and (value['state_token'] not in STATE_IDS
                or type(value['state_token_id']) is not int
                or STATE_IDS[value['state_token']] != value['state_token_id']):
            raise ValueError('Invalid accepted SoulX state')
        end, observed = value['processed_until'], value['audio_observed_until']
        if type(end) is not int or type(observed) is not int or not 0 <= end <= observed:
            raise ValueError('Invalid audio observation range')
        with self.changed:
            old = self.latest[key]
            if old['status'] != 'open':
                raise ValueError('Cannot update a closed user turn')
            if end <= old['processed_until']:
                raise ValueError('Audio frame is duplicated or out of order')
            value['published_at'] = time.monotonic()
            return self._store(key, value)

    def get_user_turn(self, session_id, turn_id):
        """Return one atomic copy; later writes never mutate an existing reader's copy."""
        key = self._key(session_id, turn_id)
        with self.changed:
            return deepcopy(self.latest[key])

    def close_user_turn(self, session_id, turn_id, reason):
        """Preserve the final online observation and mark its logical turn closed."""
        key = self._key(session_id, turn_id)
        if not isinstance(reason, str) or not reason:
            raise ValueError('Close requires a reason')
        with self.changed:
            value = deepcopy(self.latest[key])
            if value['status'] == 'closed':
                return value
            value.update(status='closed', close_reason=reason, published_at=time.monotonic())
            return self._store(key, value)

    def release_closed_turn(self, session_id, turn_id):
        key = self._key(session_id, turn_id)
        with self.changed:
            if self.latest[key]['status'] != 'closed':
                raise ValueError('Cannot release an active user turn')
            del self.latest[key]
