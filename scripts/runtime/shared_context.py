"""Publish bounded, atomic frontend observations and revision-aware user turns."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
import json
import threading
import time


STATE_IDS = {'<|user_idle|>': 151680, '<|user_nonidle|>': 151681,
             '<|user_backchannel|>': 151677, '<|user_complete|>': 151676,
             '<|user_incomplete|>': 151678}
KINDS = {'asr_observation', 'control_observation', 'user_transcript',
         'user_state', 'frontend_lifecycle'}


class CursorGap(ValueError):
    """An event range has expired; consumers must explicitly resynchronize."""


class SharedContext:
    """Own a revision-aware materialized view and one ordered event stream."""

    def __init__(self, max_updates=4096, max_bytes=16 * 1024 * 1024,
                 max_event_bytes=256 * 1024, max_turns=128):
        if min(max_updates, max_bytes, max_event_bytes, max_turns) < 1:
            raise ValueError('Context limits must be positive')
        self.max_updates, self.max_bytes = max_updates, max_bytes
        self.max_event_bytes, self.max_turns = max_event_bytes, max_turns
        self.events = deque()
        self.event_index, self.latest, self.producers = {}, {}, {}
        self.sequence, self.bytes = 0, 0
        self.changed = threading.Condition(threading.RLock())

    @staticmethod
    def _digest(event):
        return hashlib.sha256(json.dumps(event, ensure_ascii=False, sort_keys=True,
                                         allow_nan=False).encode()).hexdigest()

    def commit_frontend_events(self, events):
        """Validate the entire transaction before making any event visible."""
        values = deepcopy(list(events))
        if not values or len(values) > self.max_updates:
            raise ValueError('Empty or oversized transaction')
        with self.changed:
            views = self.latest.copy()
            producers = self.producers.copy()
            pending, known, results = [], dict(self.event_index), []
            for value in values:
                required = {'schema_version', 'event_id', 'kind', 'session_id', 'turn_id',
                            'source', 'producer_seq', 'asr_generation', 'controller_generation',
                            'received_at', 'clock_id'}
                if not required <= value.keys() or value['schema_version'] != 1:
                    raise ValueError('Incomplete frontend event')
                if value['kind'] not in KINDS or not isinstance(value['event_id'], str):
                    raise ValueError('Unsupported frontend event')
                if 'event_seq' in value or 'published_at' in value:
                    raise ValueError('Only Context assigns publication metadata')
                digest = self._digest(value)
                old = known.get(value['event_id'])
                if old:
                    if old['_digest'] != digest:
                        raise ValueError('Conflicting duplicate event ID')
                    results.append({'status': 'duplicate', 'event_seq': old['event_seq']})
                    continue
                producer = (value['session_id'], value.get('producer_id', value['source']))
                if type(value['producer_seq']) is not int or value['producer_seq'] != producers.get(producer, 0) + 1:
                    raise ValueError('Producer sequence gap or expired duplicate')
                producers[producer] = value['producer_seq']
                for reference in value.get('depends_on', []):
                    dependency = known.get(reference)
                    if dependency is None or dependency['session_id'] != value['session_id'] or dependency['turn_id'] != value['turn_id']:
                        raise ValueError('Missing or cross-turn event dependency')
                key = value['session_id'], value['turn_id']
                view = deepcopy(views.get(key, {'transcript': None, 'states': [], 'last_state': None}))
                generation = view.get('controller_generation', value['controller_generation'])
                if value['kind'] == 'frontend_lifecycle' and value.get('reason') == 'controller_reset':
                    if value['controller_generation'] != generation + 1:
                        raise ValueError('Controller reset generation gap')
                elif value['controller_generation'] != generation:
                    raise ValueError('Stale or unregistered controller generation')
                view['controller_generation'] = value['controller_generation']
                if value['kind'] == 'user_transcript':
                    self._validate_transcript(value, view['transcript'])
                    view['transcript'] = value
                elif value['kind'] == 'user_state':
                    token = value['token']
                    if value['accepted'] and (token not in STATE_IDS or value['token_id'] != STATE_IDS[token]):
                        raise ValueError('Invalid accepted state token')
                    basis = value['basis']
                    current = view['transcript']
                    if current is None or current['status'] == 'closed':
                        raise ValueError('State requires an open turn')
                    if basis['transcript_version'] != current['version'] or basis['asr_version'] != current['asr_version']:
                        raise ValueError('State transcript basis does not match the producer view')
                    control_id = basis.get('control_event_id')
                    if control_id:
                        control = known.get(control_id)
                        if (not control or control['kind'] != 'control_observation'
                                or control['control_revision'] != basis['control_revision']
                                or control['event_seq'] != basis['control_event_seq']):
                            raise ValueError('Invalid state control basis')
                    if value['accepted']:
                        view['last_state'] = value
                    view['states'] = [value]
                if value['turn_id'] is not None and key not in views and len(views) >= self.max_turns:
                    raise RuntimeError('Context turn limit exceeded; explicitly release a closed turn')
                value.update(event_seq=self.sequence + len(pending) + 1,
                             published_at=time.monotonic(), _digest=digest)
                size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
                if size > self.max_event_bytes:
                    raise RuntimeError('Context event byte limit exceeded')
                value['_bytes'] = size
                known[value['event_id']] = value
                if value['turn_id'] is not None:
                    view['event_seq'] = value['event_seq']
                    views[key] = view
                pending.append(value)
                results.append({'status': 'published', 'event_seq': value['event_seq']})
            if sum(v['_bytes'] for v in pending) > self.max_bytes:
                raise RuntimeError('Context transaction byte limit exceeded')
            self.latest, self.producers = views, producers
            for value in pending:
                self.events.append(value)
                self.event_index[value['event_id']] = value
                self.bytes += value['_bytes']
                self.sequence = value['event_seq']
            while len(self.events) > self.max_updates or self.bytes > self.max_bytes:
                evicted = self.events.popleft()
                self.bytes -= evicted['_bytes']
                del self.event_index[evicted['event_id']]
            self.changed.notify_all()
            return results

    @staticmethod
    def _validate_transcript(value, old):
        if value['source'] != 'sensevoice_small' or value['status'] not in ('open', 'closed'):
            raise ValueError('Unsupported transcript source or lifecycle')
        if not isinstance(value['text'], str) or len(value['text']) > 65536:
            raise ValueError('Invalid transcript text or length')
        if type(value['version']) is not int or type(value['asr_version']) is not int:
            raise ValueError('Invalid transcript version type')
        if old is None:
            if value['version'] != 0 or value['asr_version'] != 0 or value['text'] or value['status'] != 'open':
                raise ValueError('A turn must open at empty version zero')
            return
        if old['status'] == 'closed' or value['version'] != old['version'] + 1:
            raise ValueError('Transcript version gap or update after close')
        if value['asr_generation'] != old['asr_generation']:
            raise ValueError('ASR source generation changed within a turn')
        changed = value['text'] != old['text']
        if value['asr_version'] != old['asr_version'] + int(changed):
            raise ValueError('ASR version must count actual text changes')
        if changed:
            offset = value['replace_from']
            if (value['base_asr_version'] != old['asr_version'] or type(offset) is not int
                    or not 0 <= offset <= len(old['text'])
                    or old['text'][:offset] + value['replacement'] != value['text']):
                raise ValueError('Transcript patch cannot reconstruct the new snapshot')
        if value['status'] == 'closed' and (changed or not value.get('close_reason')):
            raise ValueError('Close must preserve online text and include a reason')

    @staticmethod
    def _public(value):
        return deepcopy({k: v for k, v in value.items() if not k.startswith('_')})

    def get_user_turn(self, session_id, turn_id, at_event_seq=None):
        with self.changed:
            if at_event_seq is not None:
                if type(at_event_seq) is not int or not 1 <= at_event_seq <= self.sequence:
                    raise CursorGap('Historical read requires an existing committed sequence')
                self._check_cursor(at_event_seq - 1)
                values = [v for v in self.events if v['session_id'] == session_id
                          and v['turn_id'] == turn_id and v['event_seq'] <= at_event_seq]
                transcripts = [v for v in values if v['kind'] == 'user_transcript']
                if not transcripts:
                    raise CursorGap('Requested transcript history is no longer retained')
                view = {'transcript': transcripts[-1],
                        'states': [v for v in values if v['kind'] == 'user_state'],
                        'event_seq': at_event_seq}
            else:
                view = deepcopy(self.latest[(session_id, turn_id)])
                view['cursor'] = self.sequence
            view['history_start_seq'] = self.events[0]['event_seq'] if self.events else self.sequence + 1
            referenced = [view.get('transcript')] + view.get('states', [])
            view['history_complete'] = all(v is None or v['event_id'] in self.event_index
                                          and all(d in self.event_index for d in v.get('depends_on', []))
                                          for v in referenced)
            return json.loads(json.dumps(view, default=str), object_hook=lambda obj: {k: v for k, v in obj.items() if not k.startswith('_')})

    def _check_cursor(self, cursor):
        first = self.events[0]['event_seq'] if self.events else self.sequence + 1
        if type(cursor) is not int or cursor < first - 1 or cursor > self.sequence:
            raise CursorGap('Context cursor expired or invalid; explicitly resynchronize')

    def read_frontend_updates(self, session_id, after_event_seq=0):
        with self.changed:
            self._check_cursor(after_event_seq)
            return {'updates': [self._public(v) for v in self.events
                                if v['session_id'] == session_id and v['event_seq'] > after_event_seq],
                    'cursor': self.sequence}

    def read_user_transcript_updates(self, session_id, after_event_seq=0):
        batch = self.read_frontend_updates(session_id, after_event_seq)
        batch['updates'] = [v for v in batch['updates'] if v['kind'] == 'user_transcript']
        return batch

    def publish_user_transcript(self, snapshot):
        return self.commit_frontend_events([snapshot])[0]

    def publish_user_state(self, event):
        return self.commit_frontend_events([event])[0]

    def release_closed_turn(self, session_id, turn_id):
        with self.changed:
            key = session_id, turn_id
            if self.latest[key]['transcript']['status'] != 'closed':
                raise ValueError('Cannot release an active turn')
            transcript = self.latest[key]['transcript']
            producer = session_id, transcript.get('producer_id', transcript['source'])
            self.producers.pop(producer, None)
            del self.latest[key]


class FrontendConsumer:
    """A read-only consumer with its own cursor and replacement-based turn views."""

    def __init__(self, session_id):
        self.session_id, self.cursor = session_id, 0
        self.turns, self.states = {}, deque(maxlen=4096)

    def consume(self, context):
        batch = context.read_frontend_updates(self.session_id, self.cursor)
        for event in batch['updates']:
            if event['kind'] == 'user_transcript':
                self.turns[event['turn_id']] = deepcopy(event)
            elif event['kind'] == 'user_state':
                self.states.append(deepcopy(event))
        self.cursor = batch['cursor']
        return batch['updates']

    def resynchronize(self, context, turn_id):
        view = context.get_user_turn(self.session_id, turn_id)
        self.turns[turn_id] = view['transcript']
        self.cursor = view['cursor']
        self.states.clear()
        return view
