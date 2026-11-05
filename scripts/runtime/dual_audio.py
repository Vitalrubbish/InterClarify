"""Bound continuous PCM and advance native control/X2 behind a 160 ms barrier."""
from __future__ import annotations

from copy import deepcopy
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import numpy as np

try:
    from .native_soulx import pcm_digest
except ImportError:
    from native_soulx import pcm_digest


class PCMLedger:
    """Keep one immutable, contiguous source copy with explicit padding spans."""

    def __init__(self, clock=time.monotonic):
        self.start = self.end = 0
        self.eof = False
        self.clock, self.eof_at, self._arrivals = clock, None, deque()
        self._audio = np.empty(0, dtype=np.float32)
        self._lock = threading.RLock()

    @staticmethod
    def digest(audio):
        return pcm_digest(audio)

    def append(self, audio):
        values = np.asarray(audio)
        if values.dtype != np.float32 or values.ndim != 1 or not np.isfinite(values).all():
            raise ValueError('PCM must be finite mono float32 at 16 kHz')
        if values.size and np.max(np.abs(values)) > 1:
            raise ValueError('PCM amplitude exceeds the frozen unit-gain contract')
        with self._lock:
            if self.eof:
                raise RuntimeError('PCM after EOF')
            begin = self.end
            self._audio = np.concatenate([self._audio, values])
            self.end += len(values)
            arrived_at = self.clock()
            if len(values):
                self._arrivals.append((self.end, arrived_at))
            return {'start': begin, 'end': self.end, 'sha256': self.digest(values), 'arrived_at': arrived_at}

    def finish(self):
        with self._lock:
            self.eof = True
            self.eof_at = self.clock()

    def ready_at(self, required_end):
        with self._lock:
            if required_end > self.end:
                if not self.eof:
                    raise BufferError('Input is not yet ready')
                return self.eof_at
            for end, at in self._arrivals:
                if end >= required_end:
                    return at
            raise ValueError('Input readiness has no retained arrival record')

    def window(self, begin, end):
        with self._lock:
            if end <= begin or max(begin, 0) < self.start:
                raise ValueError('PCM window is invalid or was already released')
            if end > self.end and not self.eof:
                raise BufferError('Real lookahead has not arrived')
            parts, spans = [], []
            if begin < 0:
                count = min(end, 0) - begin
                parts.append(np.zeros(count, np.float32))
                spans.append({'kind': 'synthetic', 'reason': 'x2_left_padding', 'samples': count})
            left, right = max(begin, 0), min(end, self.end)
            if left < right:
                parts.append(self._audio[left - self.start:right - self.start].copy())
                spans.append({'kind': 'real', 'start': left, 'end': right, 'samples': right - left})
            if end > self.end:
                count = end - max(begin, self.end)
                parts.append(np.zeros(count, np.float32))
                spans.append({'kind': 'synthetic', 'reason': 'eof_right_padding', 'samples': count})
            return np.concatenate(parts), spans

    def discard_before(self, sample):
        with self._lock:
            if not self.start <= sample <= self.end:
                raise ValueError('Invalid PCM release cursor')
            self._audio = self._audio[sample - self.start:].copy()
            self.start = sample
            while self._arrivals and self._arrivals[0][0] <= sample:
                self._arrivals.popleft()

    @property
    def nbytes(self):
        with self._lock:
            return self._audio.nbytes


class StepBarrier:
    """Reject stale/missing acknowledgements and retain both lane timings."""

    def __init__(self, clock=time.monotonic, session_id='session', turn_id='turn'):
        self.session_id, self.turn_id = session_id, turn_id
        self.clock, self.step_id, self.epoch = clock, 0, 0
        self.current, self.cancelled = None, False

    def begin(self, source_start, source_end, input_ready_at=None):
        if self.cancelled or self.current is not None:
            raise RuntimeError('Previous step has not released or barrier is cancelled')
        self.current = {'session_id': self.session_id, 'turn_id': self.turn_id,
                        'epoch': self.epoch, 'step_id': self.step_id,
                        'source_start': source_start, 'source_end': source_end,
                        'input_ready_at': self.clock() if input_ready_at is None else input_ready_at,
                        'started_at': self.clock(), 'receipts': {},
                        'staged': {'state': None, 'text': [], 'progress': []}}
        return self.epoch, self.step_id

    def acknowledge(self, ticket, receipt):
        if self.cancelled or self.current is None or ticket != (self.epoch, self.step_id):
            raise RuntimeError('Stale barrier receipt')
        lane = receipt['lane']
        if lane not in ('asr', 'controller') or lane in self.current['receipts'] or receipt['step_id'] != self.step_id:
            raise ValueError('Invalid or duplicate barrier receipt')
        if receipt['completed_at'] < self.current['input_ready_at']:
            raise ValueError('Receipt predates the current step')
        self.current['receipts'][lane] = deepcopy(receipt)

    def release(self, snapshot):
        if self.cancelled or self.current is None or set(self.current['receipts']) != {'asr', 'controller'}:
            raise RuntimeError('Both lanes must actually complete before release')
        if (snapshot['step_id'] != self.step_id or snapshot['session_id'] != self.session_id
                or snapshot['turn_id'] != self.turn_id or snapshot['status'] != 'open'
                or snapshot['batch_published_at'] < max(row['completed_at'] for row in self.current['receipts'].values())):
            raise ValueError('A successfully published joint snapshot is required')
        result = self.current
        result['batch_published_at'] = snapshot['batch_published_at']
        result['lanes_completed_at'] = max(row['completed_at'] for row in result['receipts'].values())
        result['released_at'] = self.clock()
        result['wait_seconds'] = {lane: result['lanes_completed_at'] - row['completed_at']
                                  for lane, row in result['receipts'].items()}
        self.current = None
        self.step_id += 1
        return result

    def cancel(self):
        self.cancelled = True
        self.epoch += 1


class DualAudioFrontend:
    """Accept PCM independently of model execution; one worker advances both lanes."""

    def __init__(self, controller, asr, *, context, clock=time.monotonic,
                 order=('controller', 'asr'), realtime=True, concurrent=False, pcm_limit_bytes=4 * 2**20):
        if tuple(order) not in (('controller', 'asr'), ('asr', 'controller')):
            raise ValueError('Each lane must run exactly once per cycle')
        self.controller, self.asr, self.clock, self.context = controller, asr, clock, context
        if type(pcm_limit_bytes) is not int or not 4 * 2**20 <= pcm_limit_bytes <= 16 * 2**20:
            raise ValueError('PCM capacity must be an integer between 4 and 16 MiB')
        self.pcm_limit_bytes = pcm_limit_bytes
        self.realtime = realtime
        self.concurrent = concurrent
        if (controller.session_id, controller.turn_id) != (asr.session_id, asr.turn_id):
            raise ValueError('Controller and ASR must belong to the same logical turn')
        initial = context.get_user_turn(controller.session_id, controller.turn_id)
        if (initial['source'] != 'x2_streaming_asr' or initial.get('publication_mode') != 'joint'
                or initial['status'] != 'open'
                or initial['step_id'] != -1 or controller.processed_until or asr.frame_index):
            raise ValueError('Frontend requires a fresh open independent-ASR turn')
        if controller.on_state or asr.on_text or asr.on_progress:
            raise ValueError('Lane callbacks belong exclusively to the batch stager')
        self.order, self.ledger = order, PCMLedger(clock)
        self.barrier = StepBarrier(clock, controller.session_id, controller.turn_id)
        self.closed, self.failure, self.started_at = False, None, None
        self.close_failure = None
        self._state_lock, self._worker = threading.RLock(), threading.Lock()
        self.last_step = None
        controller_live, asr_live = controller.is_live, asr.is_live
        controller.is_live = lambda: not self.closed and controller_live()
        asr.is_live = lambda: not self.closed and asr_live()
        controller.reserve_pcm = self._reserve_pcm
        controller.on_state = lambda row: self._stage('state', row)
        asr.on_text = lambda row: self._stage('text', row)
        asr.on_progress = lambda row: self._stage('progress', row)

    def _stage(self, kind, row):
        with self._state_lock:
            current = self.barrier.current
            if self.closed or current is None or any(row.get(k) != current[k]
                    for k in ('session_id', 'turn_id', 'step_id')):
                raise RuntimeError('Late callback cannot enter the current batch')
            staged = current['staged']
            if kind == 'state':
                if staged[kind] is not None:
                    raise ValueError('Duplicate controller callback')
                staged[kind] = deepcopy(row)
            else:
                if len(staged[kind]) >= 2:
                    raise ValueError('Batch staging capacity exceeded')
                staged[kind].append(deepcopy(row))

    def _reserve_pcm(self, additional_bytes):
        with self._state_lock:
            if self.closed:
                raise RuntimeError('Frontend was cancelled before PCM allocation')
            if self.ledger.nbytes + self.controller.pcm_bytes() + additional_bytes > self.pcm_limit_bytes:
                raise MemoryError(f'Model PCM allocation would exceed {self.pcm_limit_bytes} bytes')

    def _check_bounds(self):
        if self.ledger.nbytes + self.controller.pcm_bytes() > self.pcm_limit_bytes:
            raise MemoryError(f'Total PCM exceeded {self.pcm_limit_bytes} bytes')

    def append_pcm(self, audio):
        try:
            with self._state_lock:
                if self.closed:
                    raise RuntimeError('Frontend is closed')
                # Check allocation before copying an oversized transport packet.
                if self.ledger.nbytes + np.asarray(audio).nbytes + self.controller.pcm_bytes() > self.pcm_limit_bytes:
                    raise MemoryError('Transport packet exceeds total PCM bound')
                packet = self.ledger.append(audio)
                if self.started_at is None:
                    self.started_at = self.clock() - self.ledger.end / 16000
                self._check_bounds()
                return packet
        except Exception as exc:
            self.cancel(str(exc))
            raise

    def finish_input(self):
        with self._state_lock:
            if self.closed:
                raise RuntimeError('Frontend is closed')
            self.ledger.finish()

    def _advance_lane(self, lane, ticket):
        try:
            if self.closed:
                raise RuntimeError('Step cancelled before lane execution')
            if lane == 'controller':
                receipt = self.controller.step(self.ledger, ticket[1])
            else:
                frames = []
                for _ in range(2):
                    if self.ledger.eof and self.asr.frame_index * 1280 >= self.ledger.end:
                        break
                    self._reserve_pcm(1680 * 4)
                    frames.append(self.asr.step(self.ledger, ticket[1]))
                if not frames:
                    raise RuntimeError('EOF without an ASR completion cannot release a step')
                receipt = {'lane': 'asr', 'session_id': self.asr.session_id,
                           'turn_id': self.asr.turn_id, 'step_id': ticket[1], 'frames': frames,
                           'terminal': self.ledger.eof and self.asr.processed_until == self.ledger.end,
                           'processed_until': self.asr.processed_until, 'completed_at': self.clock()}
            with self._state_lock:
                self.barrier.acknowledge(ticket, receipt)
                self._check_bounds()
        except Exception as exc:
            self.cancel(str(exc))
            raise

    def advance(self):
        if not self._worker.acquire(blocking=False):
            raise RuntimeError('Only one scheduling worker is allowed')
        try:
            with self._state_lock:
                if self.closed:
                    raise RuntimeError('Frontend is closed')
                if self.context.get_user_turn(self.controller.session_id, self.controller.turn_id)['status'] != 'open':
                    raise RuntimeError('Logical user turn is closed')
                self._check_bounds()
                source_start = self.barrier.step_id * 2560
                if self.ledger.eof and source_start >= self.ledger.end:
                    return None
                required = max(source_start + 2760, self.controller.submitted_until + 2560)
                if not self.ledger.eof and self.ledger.end < required:
                    return None
                ticket = self.barrier.begin(source_start, min(source_start + 2560, self.ledger.end),
                                            self.ledger.ready_at(required))
            if self.concurrent:
                # Joining the bounded helper also fences cancellation before detach.
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix='frontend-lane') as executor:
                    pending = executor.submit(self._advance_lane, self.order[0], ticket)
                    self._advance_lane(self.order[1], ticket)
                    pending.result()
            else:
                for lane in self.order:
                    self._advance_lane(lane, ticket)
            with self._state_lock:
                if self.closed:
                    raise RuntimeError('Frontend closed before joint publication')
                batch = self.barrier.current
                batch.update(input_end=self.ledger.end, input_eof=self.ledger.eof)
                commit_started = self.clock()
                snapshot = self.context.publish_joint_batch(batch)
                result = self.barrier.release(snapshot)
                result.update(commit_started_at=commit_started, commit_completed_at=self.clock(),
                              commit_seconds=self.clock() - commit_started,
                              lane_compute_seconds={
                                  'controller': batch['receipts']['controller']['completed_at'] -
                                                batch['receipts']['controller']['started_at'],
                                  'asr': sum(row['completed_at'] - row['started_at']
                                             for row in batch['receipts']['asr']['frames'])})
                self.last_step = deepcopy(result)
                retain = min(self.controller.processed_until, max(0, self.asr.frame_index * 1280 - 200))
                self.ledger.discard_before(retain)
            return result
        except Exception as exc:
            self.cancel(str(exc))
            raise
        finally:
            self._worker.release()

    def cancel(self, reason='runtime_cancel'):
        with self._state_lock:
            if not self.closed:
                self.closed, self.failure = True, reason
                self.barrier.cancel()
                try:
                    self.context.close_user_turn(self.controller.session_id, self.controller.turn_id, reason)
                except Exception as exc:
                    self.close_failure = str(exc)
        self.controller.cancel()
        self.asr.cancel()

    def close(self):
        self.cancel('runtime_close')

    def diagnostics(self):
        with self._state_lock:
            snapshot = self.context.get_user_turn(self.controller.session_id, self.controller.turn_id)
            return {'closed': self.closed, 'reason': self.failure, 'close_failure': self.close_failure,
                    'input_end': self.ledger.end,
                    'input_eof': self.ledger.eof, 'pcm_limit_bytes': self.pcm_limit_bytes, 'pcm_bytes': self.ledger.nbytes + self.controller.pcm_bytes(),
                    'controller_processed_until': self.controller.processed_until,
                    'controller_state': deepcopy(self.controller._frame),
                    'controller_events': deepcopy(self.controller._events),
                    'controller_failure': self.controller.failure,
                    'asr': self.asr.diagnostics(), 'last_step': deepcopy(self.last_step),
                    'pending_step': deepcopy(self.barrier.current), 'snapshot': snapshot,
                    'unprocessed_real_samples': {
                        'controller': self.ledger.end - self.controller.processed_until,
                        'asr': self.ledger.end - self.asr.processed_until}}
