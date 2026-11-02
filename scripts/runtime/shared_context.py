"""Atomically replace each user turn's current transcript and audio state."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import threading
import time


STATE_IDS = {'<|user_idle|>': 151680, '<|user_nonidle|>': 151681,
             '<|user_backchannel|>': 151677, '<|user_complete|>': 151676,
             '<|user_incomplete|>': 151678}
SERVICE_STATES = (None, 'idle', 'nonidle', 'speak', 'blank')
COMPLETION_SOURCES = (None, 'model_complete', 'wait_fallback')
COMPLETION_FIELDS = {'completion_id', 'completion_status', 'completion_target_sample',
                     'completion_deadline', 'completion_ready_at', 'completion_committed_groups',
                     'completion_reason', 'completion_available_at', 'completion_generation'}
SERVICE_FIELDS = {'service_state': None, 'service_completion_source': None,
                  'speech_detected': False, 'service_text': ''}
TRANSCRIPT_SOURCES = ('sensevoice_small', 'nemotron', 'x2_streaming_asr')


class SharedContext:
    """Keep one bounded current observation per logical user turn, without history."""

    def __init__(self, max_turns=128, max_chars=65536, max_snapshot_bytes=256 * 1024,
                 clock=time.monotonic):
        if any(type(value) is not int or value < 1
               for value in (max_turns, max_chars, max_snapshot_bytes)):
            raise ValueError('Context limits must be positive integers')
        self.max_turns, self.max_chars = max_turns, max_chars
        self.max_snapshot_bytes = max_snapshot_bytes
        self.clock = clock
        self.latest = {}
        self._closed_keys = set()
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

    def open_user_turn(self, session_id, turn_id, source='sensevoice_small', *, publication_mode=None):
        """Fix one ASR source for the entire logical turn."""
        key = self._key(session_id, turn_id)
        if source not in TRANSCRIPT_SOURCES:
            raise ValueError('Unsupported transcript source')
        mode = publication_mode or ('joint' if source == 'x2_streaming_asr' else 'legacy_frame')
        if mode not in ('joint', 'legacy_frame') or (mode == 'joint' and source != 'x2_streaming_asr'):
            raise ValueError('Unsupported publication mode')
        with self.changed:
            if key in self.latest:
                raise ValueError('User turn already exists')
            if len(self.latest) >= self.max_turns:
                raise RuntimeError('Context turn limit exceeded')
            value = {'session_id': session_id, 'turn_id': turn_id, 'source': source,
                     'text': '', 'state_token': None, 'state_token_id': None,
                     'state_accepted': False, 'rejection_reason': 'initializing',
                     'processed_until': 0, 'audio_observed_until': 0,
                     'assembly_status': 'empty', 'coverage_complete': False,
                     'status': 'open', 'published_at': self.clock(),
                     **SERVICE_FIELDS}
            value['publication_mode'] = mode
            if mode == 'joint':
                value.update(step_id=-1, committed_groups=0, batch_published_at=None,
                             text_available_at=None, text_published_at=None, text_observed_until=0,
                             state_available_at=None, state_published_at=None,
                             state_processed_until=0, state_observed_until=0,
                             asr_processed_until=0, asr_observed_until=0,
                             asr_progress_available_at=None, completion_id=None,
                             completion_status='none', tail_status='unknown')
            return self._store(key, value)

    def publish_user_frame(self, frame):
        """Publish a complete processed-audio observation, including text corrections."""
        value = deepcopy(frame)
        required = {'session_id', 'turn_id', 'source', 'text', 'state_token', 'state_token_id',
                    'state_accepted', 'processed_until', 'audio_observed_until',
                    'coverage_complete', 'assembly_status', 'status'}
        if not required <= value.keys():
            raise ValueError('Incomplete user frame')
        for name, default in SERVICE_FIELDS.items():
            value.setdefault(name, default)
        if {'version', 'asr_version', 'replace_from', 'replacement', 'event_seq'} & value.keys():
            raise ValueError('User frames contain current values, not transcript revisions')
        key = self._key(value['session_id'], value['turn_id'])
        if value['source'] not in TRANSCRIPT_SOURCES or value['status'] != 'open':
            raise ValueError('Unsupported user frame source or lifecycle')
        if not isinstance(value['text'], str):
            raise ValueError('Transcript must be a string')
        if type(value['state_accepted']) is not bool or type(value['coverage_complete']) is not bool:
            raise ValueError('Invalid user frame flags')
        if value['state_accepted'] and (value['state_token'] not in STATE_IDS
                or type(value['state_token_id']) is not int
                or STATE_IDS[value['state_token']] != value['state_token_id']):
            raise ValueError('Invalid accepted SoulX state')
        if value['service_state'] not in SERVICE_STATES:
            raise ValueError('Invalid official service state')
        if value['service_completion_source'] not in COMPLETION_SOURCES:
            raise ValueError('Invalid official completion source')
        if type(value['speech_detected']) is not bool:
            raise ValueError('Invalid speech detection flag')
        if not isinstance(value['service_text'], str) or len(value['service_text']) > self.max_chars:
            raise ValueError('Invalid official service text')
        source = value['service_completion_source']
        if source is not None and value['service_state'] != 'speak':
            raise ValueError('Completion signal requires the official speak state')
        if source == 'model_complete' and (value['state_token'] != '<|user_complete|>'
                or not value['state_accepted'] or not value['speech_detected']):
            raise ValueError('Model completion must be an accepted native complete with speech')
        if source == 'wait_fallback' and value['state_token'] == '<|user_complete|>':
            raise ValueError('Wait fallback cannot rewrite a native complete')
        if value.get('rejection_reason') == 'no_speech' and (value['state_token'] != '<|user_complete|>'
                or value['speech_detected']):
            raise ValueError('No-speech rejection only applies to an unconfirmed native complete')
        end, observed = value['processed_until'], value['audio_observed_until']
        if type(end) is not int or type(observed) is not int or not 0 <= end <= observed:
            raise ValueError('Invalid audio observation range')
        with self.changed:
            old = self.latest[key]
            if old['publication_mode'] != 'legacy_frame':
                raise ValueError('Independent X2 turns require a joint batch')
            if value['source'] != old['source']:
                raise ValueError('Transcript source cannot change within a turn')
            if key in self._closed_keys or old['status'] != 'open':
                raise ValueError('Cannot update a closed user turn')
            if end <= old['processed_until']:
                raise ValueError('Audio frame is duplicated or out of order')
            value['published_at'] = self.clock()
            value['publication_mode'] = old['publication_mode']
            return self._store(key, value)

    @staticmethod
    def _timestamp(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid monotonic timestamp')
        return value

    def publish_joint_batch(self, batch):
        """Validate two completed lanes, then merge only frontend fields atomically."""
        batch = deepcopy(batch)
        key = self._key(batch['session_id'], batch['turn_id'])
        step = batch['step_id']
        start, end, input_end = batch['source_start'], batch['source_end'], batch['input_end']
        if (type(step) is not int or step < 0 or type(start) is not int
                or type(end) is not int or type(input_end) is not int
                or start != step * 2560 or not start < end <= start + 2560
                or end > input_end or type(batch['input_eof']) is not bool
                or (end < start + 2560 and (not batch['input_eof'] or end != input_end))):
            raise ValueError('Invalid source batch range')
        receipts = batch['receipts']
        if set(receipts) != {'controller', 'asr'}:
            raise ValueError('Both lane receipts are required')
        identity = dict(session_id=key[0], turn_id=key[1], step_id=step)

        def identify(row):
            if any(row.get(k) != v for k, v in identity.items()):
                raise ValueError('Receipt belongs to another batch or turn')

        ready = self._timestamp(batch['input_ready_at'])
        started = self._timestamp(batch['started_at'])
        if started < ready:
            raise ValueError('Batch started before input readiness')
        for lane, row in receipts.items():
            identify(row)
            if row['lane'] != lane or self._timestamp(row['completed_at']) < started:
                raise ValueError('Lane has not completed this batch')
        control, asr = receipts['controller'], receipts['asr']
        state = control['state']
        identify(state)
        staged = batch['staged']
        if staged['state'] != state:
            raise ValueError('Missing or conflicting state callback')
        available = self._timestamp(state['state_available_at'])
        control_started = self._timestamp(control['started_at'])
        if not started <= control_started <= available <= control['completed_at']:
            raise ValueError('State availability is outside native execution')
        token = state['state_token']
        if (type(state['state_accepted']) is not bool
                or (state['state_accepted'] and token not in STATE_IDS)
                or type(state['controller_generation']) is not int
                or state['controller_generation'] < 0
                or type(control['generation_after']) is not int
                or control['generation_after'] not in (state['controller_generation'], state['controller_generation'] + 1)):
            raise ValueError('Invalid native state or generation')

        def progress(processed, observed):
            if (type(processed) is not int or type(observed) is not int
                    or not 0 <= processed <= observed <= input_end):
                raise ValueError('Invalid real sample progress')

        def spans(items, length):
            count, real_until = 0, 0
            for item in items:
                n = item['samples']
                if type(n) is not int or n < 0:
                    raise ValueError('Invalid PCM provenance length')
                count += n
                if item['kind'] == 'real':
                    left, right = item['start'], item['end']
                    if (type(left) is not int or type(right) is not int
                            or not 0 <= left < right <= input_end or right - left != n):
                        raise ValueError('Invalid real PCM provenance')
                    real_until = max(real_until, right)
                elif item['kind'] != 'synthetic' or not item.get('reason'):
                    raise ValueError('Padding requires an explicit reason')
            if count != length:
                raise ValueError('PCM provenance does not cover the native window')
            return real_until

        cp, co = state['state_processed_until'], state['state_observed_until']
        progress(cp, co)
        windows = control['windows']
        ends = {name: spans(windows[name]['spans'], length)
                for name, length in (('main', 2560), ('lookback', 15360), ('lookahead', 640))}
        if cp != control['processed_until'] or ends['main'] != cp or max(cp, ends['lookahead']) != co:
            raise ValueError('Native progress differs from actual sample spans')
        frames = asr['frames']
        if len(frames) != (end - start + 1279) // 1280 or len(staged['progress']) != len(frames):
            raise ValueError('Missing or extra 80 ms steps')
        text_rows = staged['text']
        if len(text_rows) > len(frames):
            raise ValueError('Too many closed text callbacks')
        previous_time, previous_groups = started, None
        for index, row in enumerate(frames):
            identify(row)
            frame_index = step * 2 + index
            ap, ao = row['asr_processed_until'], row['asr_observed_until']
            progress(ap, ao)
            if (row['frame_index'] != frame_index or row['lane'] != 'asr'
                    or ap != min((frame_index + 1) * 1280, end)
                    or ao != min((frame_index + 1) * 1280 + 200, input_end)
                    or row['decoding'] is not False or row['open_group_tokens'] != []
                    or row['decision'] not in (32, 33)
                    or type(row['committed_groups']) is not int or row['committed_groups'] < 0):
                raise ValueError('X2 step has not actually completed LISTEN/DECODE')
            if spans(row['input_spans'], 1680) != ao:
                raise ValueError('X2 progress differs from actual sample spans')
            at = self._timestamp(row['asr_progress_available_at'])
            frame_started = self._timestamp(row['started_at'])
            completed = self._timestamp(row['completed_at'])
            if not previous_time <= frame_started <= at <= completed <= asr['completed_at']:
                raise ValueError('Invalid X2 completion timing')
            previous_time = completed
            if previous_groups is not None and row['committed_groups'] != previous_groups + (row['decision'] == 33):
                raise ValueError('Invalid EOS group count')
            previous_groups = row['committed_groups']
            progress_fields = (*identity, 'frame_index', 'asr_processed_until', 'asr_observed_until',
                               'committed_groups', 'asr_progress_available_at', 'decoding',
                               'open_group_tokens', 'decision')
            if staged['progress'][index] != {k: row[k] for k in progress_fields}:
                raise ValueError('Conflicting X2 progress callback')
        last = frames[-1]
        if asr['processed_until'] != last['asr_processed_until']:
            raise ValueError('ASR receipt has inconsistent progress')
        text = last['text']
        if not isinstance(text, str):
            raise ValueError('Transcript must be a string')
        if (control['service_state'] not in SERVICE_STATES
                or control['service_completion_source'] not in COMPLETION_SOURCES
                or not isinstance(control['service_text'], str)
                or len(control['service_text']) > self.max_chars
                or type(state['speech_detected_before_service']) is not bool):
            raise ValueError('Invalid native service result')
        source = control['service_completion_source']
        if (source is not None and control['service_state'] != 'speak'
                or source == 'model_complete' and (token != '<|user_complete|>'
                    or not state['state_accepted'] or not state['speech_detected_before_service'])
                or source == 'wait_fallback' and token == '<|user_complete|>'):
            raise ValueError('Service completion differs from native state')
        with self.changed:
            old = self.latest[key]
            if (old['source'] != 'x2_streaming_asr' or old['publication_mode'] != 'joint'
                    or key in self._closed_keys or old['status'] != 'open' or step != old['step_id'] + 1):
                raise ValueError('Closed, stale, duplicated or skipped joint batch')
            if (cp < old['state_processed_until'] or co < old['state_observed_until']
                    or last['asr_processed_until'] <= old['asr_processed_until']
                    or state['controller_generation'] != old.get('generation_after', 0)):
                raise ValueError('Progress or native generation moved out of sequence')
            prior_text, count, changed_rows = old['text'], old['committed_groups'], []
            prior_available, prior_observed = old['text_available_at'], old['text_observed_until']
            for row in frames:
                if row['committed_groups'] != count + (row['decision'] == 33):
                    raise ValueError('Closed groups were lost or duplicated')
                if not row['text'].startswith(prior_text) or (row['decision'] == 32 and row['text'] != prior_text):
                    raise ValueError('Transcript must append only genuine closed groups')
                if row['text'] != prior_text:
                    expected = dict(identity, frame_index=row['frame_index'],
                                    asr_processed_until=row['asr_processed_until'],
                                    asr_observed_until=row['asr_observed_until'],
                                    committed_groups=row['committed_groups'], text=row['text'],
                                    delta=row['text'][len(prior_text):], source='x2_streaming_asr',
                                    text_available_at=row['text_available_at'],
                                    text_observed_until=row['text_observed_until'])
                    changed_rows.append(expected)
                    if (not started <= self._timestamp(row['text_available_at']) <= row['asr_progress_available_at']
                            or row['text_observed_until'] != row['asr_observed_until']):
                        raise ValueError('Invalid EOS text availability')
                elif row['text_available_at'] != prior_available or row['text_observed_until'] != prior_observed:
                    raise ValueError('Unchanged text changed availability or observation range')
                prior_text, count = row['text'], row['committed_groups']
                prior_available, prior_observed = row['text_available_at'], row['text_observed_until']
            if text_rows != changed_rows:
                raise ValueError('Missing, extra or conflicting closed text callback')
            published = self._timestamp(self.clock())
            if published < max(row['completed_at'] for row in receipts.values()):
                raise ValueError('Publication predates lane completion')
            value = deepcopy(old)
            value.update(step_id=step, text=text, committed_groups=count,
                         state_token=token, state_token_id=STATE_IDS.get(token),
                         state_accepted=state['state_accepted'], rejection_reason=state['rejection_reason'],
                         controller_generation=state['controller_generation'], generation_after=control['generation_after'],
                         state_processed_until=cp, state_observed_until=co, processed_until=cp,
                         audio_observed_until=co, state_available_at=available,
                         state_published_at=published, batch_published_at=published, published_at=published,
                         asr_processed_until=last['asr_processed_until'], asr_observed_until=last['asr_observed_until'],
                         asr_progress_available_at=last['asr_progress_available_at'],
                         asr_progress_published_at=published, decoding=False, open_group_tokens=[],
                         service_state=control['service_state'], service_completion_source=source,
                         service_text=control['service_text'], speech_detected=state['speech_detected_before_service'],
                         raw_token=state['raw_token'], raw_token_id=state['raw_token_id'],
                         rule_applied=state['rule_applied'], controller_windows=windows,
                         source_start=start, source_end=end, input_end=input_end, input_eof=batch['input_eof'],
                         terminal_batch=batch['input_eof'] and end == input_end,
                         partial_batch=end - start < 2560, coverage_complete=False,
                         assembly_status='eos_closed', tail_status='unknown',
                         input_ready_at=ready, batch_started_at=started,
                         lane_completed_at={lane: row['completed_at'] for lane, row in receipts.items()},
                         asr_frames=[{k: v for k, v in row.items() if k not in ('text', 'open_group_tokens')}
                                     for row in frames])
            if text != old['text']:
                value.update(text_available_at=last['text_available_at'],
                             text_observed_until=last['text_observed_until'], text_published_at=published)
            return self._store(key, value)

    def update_completion(self, session_id, turn_id, *, expected_step_id, expected_completion_id,
                          expected_completion_status, fields):
        """Reserve one current handoff record; callers must compare the current batch."""
        key = self._key(session_id, turn_id)
        fields = deepcopy(fields)
        if not fields or fields.keys() - COMPLETION_FIELDS:
            raise ValueError('Only current completion metadata may be updated')
        with self.changed:
            old = self.latest[key]
            if (key in self._closed_keys or old['status'] != 'open' or old.get('step_id') != expected_step_id
                    or old.get('completion_id') != expected_completion_id
                    or old.get('completion_status') != expected_completion_status):
                raise ValueError('Stale completion update')
            value = dict(old, **fields)
            if value['completion_status'] not in ('none', 'pending', 'ready', 'cancelled', 'timed_out'):
                raise ValueError('Invalid completion lifecycle')
            if (value['completion_status'] != 'none'
                    and (not isinstance(value['completion_id'], str) or not value['completion_id'])):
                raise ValueError('A handoff record requires a completion identifier')
            return self._store(key, value)

    def get_user_turn(self, session_id, turn_id, *, with_timing=False):
        """Return one atomic copy; later writes never mutate an existing reader's copy."""
        key = self._key(session_id, turn_id)
        started = self.clock()
        with self.changed:
            snapshot = deepcopy(self.latest[key])
        if with_timing:
            completed = self.clock()
            return dict(snapshot=snapshot, read_started_at=started, read_completed_at=completed,
                        read_seconds=completed - started)
        return snapshot

    def close_user_turn(self, session_id, turn_id, reason):
        """Preserve the final online observation and mark its logical turn closed."""
        key = self._key(session_id, turn_id)
        if not isinstance(reason, str) or not reason:
            raise ValueError('Close requires a reason')
        with self.changed:
            value = deepcopy(self.latest[key])
            # Keep a bounded terminal fence even if close metadata cannot fit.
            self._closed_keys.add(key)
            if value['status'] == 'closed':
                return value
            value.update(status='closed', close_reason=reason, published_at=self.clock())
            if value.get('completion_status') in ('pending', 'ready'):
                value.update(completion_status='cancelled', completion_reason=reason)
            return self._store(key, value)

    def release_closed_turn(self, session_id, turn_id):
        key = self._key(session_id, turn_id)
        with self.changed:
            if key not in self._closed_keys:
                raise ValueError('Cannot release an active user turn')
            del self.latest[key]
            self._closed_keys.remove(key)
