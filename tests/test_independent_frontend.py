"""Exercise EOS publication, source identity, barriers and bounded lifecycle failures."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
sys.path.insert(0, str(ROOT / 'scripts/remote'))
from dual_audio import DualAudioFrontend, PCMLedger, StepBarrier
from independent_x2 import ClosedText, IndependentX2
from x2_streaming_probe import decode_emit
from test_native_soulx import official_model, SOURCE
from native_soulx import NativeSoulX, pcm_digest
from shared_context import SharedContext


class FakeEngine:
    def __init__(self, emissions):
        self.emissions = iter(emissions)
        self.audio = []
        self.torch = SimpleNamespace(inference_mode=nullcontext)
        self.processor = SimpleNamespace(tokenizer=SimpleNamespace(
            decode=lambda ids, **kwargs: ''.join({10: 'inter', 11: 'national', 12: 'hello world', 13: 'again'}[i] for i in ids)))
        self.join = lambda parts: ' '.join(part for part in parts if part)

    def step(self, audio, on_token):
        self.audio.append(audio.copy())
        emission = next(self.emissions)
        if emission is None:
            on_token(32, 'listen')
            return {'decision': 32}
        on_token(33, 'listen')
        values = iter(emission)
        first = next(values)
        ids, _ = decode_emit(first, lambda _: next(values), on_token, 64)
        self.groups.append(ids)
        return {'decision': 33}


class Clock:
    def __init__(self):
        self.now = 100.

    def __call__(self):
        return self.now


class X2Tests(unittest.TestCase):
    def ledger(self, count=6000):
        ledger = PCMLedger()
        ledger.append(np.linspace(-.1, .1, count, dtype=np.float32))
        return ledger

    def test_subwords_and_multiword_groups_publish_only_at_eos_then_wait_progress(self):
        text, progress = [], []
        clock = Clock()
        engine = FakeEngine([[10, 11, 2], [12, 2], None, None])
        asr = IndependentX2(engine, on_text=text.append, on_progress=progress.append, clock=clock)
        ledger = self.ledger()
        for i in range(4):
            clock.now += .08
            asr.step(ledger, i // 2)
        self.assertEqual([r['text'] for r in text], ['international', 'international hello world'])
        self.assertEqual(len(progress), 4)
        self.assertEqual([r['asr_processed_until'] for r in progress], [1280, 2560, 3840, 5120])
        self.assertEqual(asr.text_available_at, text[-1]['text_available_at'])
        self.assertGreater(progress[-1]['asr_progress_available_at'], asr.text_available_at)
        self.assertEqual(len(engine.audio[0]), 1680)
        np.testing.assert_array_equal(engine.audio[0][:200], np.zeros(200, np.float32))
        np.testing.assert_array_equal(engine.audio[1], ledger.window(1080, 2760)[0])

    def test_word_does_not_publish_and_open_tokens_survive_failure_and_eof(self):
        text, progress = [], []
        asr = IndependentX2(FakeEngine([[10, 11]]), on_text=text.append, on_progress=progress.append)
        ledger = self.ledger()
        ledger.finish()
        with self.assertRaises(StopIteration):
            asr.step(ledger, 0)
        self.assertEqual((text, progress), ([], []))
        self.assertEqual(asr.diagnostics()['open_group_tokens'], [10, 11])
        self.assertTrue(asr.diagnostics()['decoding'])
        self.assertEqual(asr.processed_until, 0)

    def test_decode_cap_fails_without_eos_and_retains_tail(self):
        asr = IndependentX2(FakeEngine([[10] * 65]))
        with self.assertRaises(RuntimeError):
            asr.step(self.ledger(), 0)
        self.assertEqual(asr.groups.text, '')
        self.assertEqual(asr.processed_until, 0)
        self.assertEqual(len(asr.open_tokens), 64)

    def test_prefix_rewrite_rejected_without_changing_text(self):
        groups = ClosedText(lambda ids: str(ids), lambda parts: ' '.join(parts))
        groups.append([10, 2])
        groups.join = lambda parts: 'replacement'
        with self.assertRaises(ValueError):
            groups.append([11, 2])
        self.assertEqual(groups.text, '[10]')
        self.assertEqual(groups.count, 1)

    def test_cancel_during_decode_rejects_late_callbacks(self):
        text, progress = [], []
        engine = FakeEngine([[10, 2]])
        asr = IndependentX2(engine, on_text=text.append, on_progress=progress.append)
        step = engine.step

        def cancel_first(audio, callback):
            asr.cancel()
            return step(audio, callback)

        engine.step = cancel_first
        with self.assertRaises(RuntimeError):
            asr.step(self.ledger(), 0)
        self.assertEqual((text, progress), ([], []))
        with self.assertRaises(RuntimeError):
            asr.step(self.ledger(), 1)


class AudioTests(unittest.TestCase):
    def test_concurrent_lanes_start_together_but_publish_only_after_both_finish(self):
        for first in ('controller', 'asr'):
            with self.subTest(first=first):
                frontend = self.make(concurrent=True)
                entered = {lane: threading.Event() for lane in ('controller', 'asr')}
                allowed = {lane: threading.Event() for lane in ('controller', 'asr')}
                finished = {lane: threading.Event() for lane in ('controller', 'asr')}
                for lane in ('controller', 'asr'):
                    component = getattr(frontend, lane)
                    original = component.step

                    def blocked(*args, _lane=lane, _original=original):
                        entered[_lane].set()
                        if not allowed[_lane].wait(5):
                            raise TimeoutError('Test lane was not released')
                        result = _original(*args)
                        finished[_lane].set()
                        return result
                    component.step = blocked
                frontend.append_pcm(np.full(2760, .1, np.float32))
                results, errors = [], []

                def drive():
                    try:
                        results.append(frontend.advance())
                    except Exception as exc:
                        errors.append(exc)
                worker = threading.Thread(target=drive)
                worker.start()
                try:
                    self.assertTrue(entered['controller'].wait(3))
                    self.assertTrue(entered['asr'].wait(3))
                    allowed[first].set()
                    self.assertTrue(finished[first].wait(3))
                    self.assertEqual(self.view(frontend)['step_id'], -1)
                    with self.assertRaises(RuntimeError):
                        frontend.advance()
                finally:
                    for event in allowed.values():
                        event.set()
                    worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(results), 1)
                self.assertEqual(self.view(frontend)['step_id'], 0)

    def test_concurrent_failure_waits_for_other_lane_before_returning(self):
        frontend = self.make(concurrent=True)
        entered, failed, release, finished = [threading.Event() for _ in range(4)]
        original = frontend.asr.step

        def blocked_asr(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test ASR was not released')
            try:
                return original(*args)
            finally:
                finished.set()

        def fail_control(*args):
            if not entered.wait(3):
                raise TimeoutError('Concurrent ASR never entered')
            failed.set()
            raise ValueError('Injected control failure')

        frontend.asr.step, frontend.controller.step = blocked_asr, fail_control
        frontend.append_pcm(np.full(2760, .1, np.float32))
        errors = []

        def drive():
            try:
                frontend.advance()
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=drive)
        worker.start()
        try:
            self.assertTrue(failed.wait(3))
            self.assertTrue(worker.is_alive())
            self.assertFalse(finished.is_set())
            self.assertEqual(self.view(frontend)['step_id'], -1)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(finished.is_set())
        self.assertTrue(errors)
        self.assertEqual(self.view(frontend)['status'], 'closed')

    def make(self, order=('controller', 'asr'), predictions=None, emissions=None, **kwargs):
        self.clock = Clock()
        controller = NativeSoulX(official_model(predictions or [99, 6] * 10),
                                 source_path=SOURCE, synchronize=lambda: None, clock=self.clock,
                                 session_id='session', turn_id='turn')
        self.addCleanup(controller.detach)
        asr = IndependentX2(FakeEngine(emissions or [None] * 20), clock=self.clock)
        context = kwargs.pop('context', SharedContext(clock=self.clock))
        context.open_user_turn('session', 'turn', 'x2_streaming_asr')
        return DualAudioFrontend(controller, asr, context=context, clock=self.clock, order=order, **kwargs)

    def test_both_orders_require_both_receipts_and_do_not_wait_for_text(self):
        for order in (('asr', 'controller'), ('controller', 'asr')):
            frontend = self.make(order)
            self.assertIsNone(frontend.advance())
            frontend.append_pcm(np.full(2760, .1, np.float32))
            row = frontend.advance()
            self.assertEqual(set(row['receipts']), {'asr', 'controller'})
            self.assertEqual(len(row['receipts']['asr']['frames']), 2)
            self.assertEqual(frontend.barrier.step_id, 1)
            self.assertIsNone(frontend.advance())
            frontend.append_pcm(np.full(2560, .2, np.float32))
            following = frontend.advance()
            self.assertGreaterEqual(following['started_at'], row['released_at'])
            self.assertEqual(frontend.asr.frame_index, 4)

    def test_real_pcm_is_identical_and_window_coordinates_are_not_assumed_equal(self):
        frontend = self.make()
        pcm = np.linspace(-.5, .5, 2760, dtype=np.float32)
        packet = frontend.append_pcm(pcm)
        pcm[:] = 0
        row = frontend.advance()
        main = row['receipts']['controller']['windows']['main']
        self.assertEqual(main['spans'][-1]['end'], 1920)
        self.assertEqual(row['receipts']['asr']['frames'][-1]['asr_observed_until'], 2760)
        original = np.linspace(-.5, .5, 2760, dtype=np.float32)
        self.assertEqual(packet['sha256'], pcm_digest(original))
        np.testing.assert_array_equal(frontend.asr.engine.audio[0][200:], original[:1480])
        actual = frontend.controller.model.trace[0]
        np.testing.assert_array_equal(actual[2][640:], original[:1920])
        np.testing.assert_array_equal(actual[3], original[1920:2560])

    def test_input_arrival_and_model_start_are_separate_times(self):
        frontend = self.make()
        frontend.append_pcm(np.zeros(2760, np.float32))
        self.clock.now += .01
        packet = frontend.append_pcm(np.zeros(2560, np.float32))
        self.clock.now += .01
        first = frontend.advance()
        second = frontend.advance()
        self.assertEqual(second['input_ready_at'], packet['arrived_at'])
        self.assertLess(second['input_ready_at'], first['released_at'])
        self.assertGreaterEqual(second['started_at'], first['released_at'])

    def view(self, frontend):
        return frontend.context.get_user_turn('session', 'turn')

    def test_first_group_and_nonidle_stay_invisible_until_both_lanes_complete(self):
        for order in (('asr', 'controller'), ('controller', 'asr')):
            frontend = self.make(order, predictions=[99, 5], emissions=[[10, 11, 2], None])
            original_engine = frontend.asr.engine.step
            observations = []

            def inspect_step(audio, callback):
                observations.append(self.view(frontend))
                self.clock.now += .01
                return original_engine(audio, callback)

            frontend.asr.engine.step = inspect_step
            original_sync = frontend.controller.synchronize

            def inspect_device():
                self.assertEqual(self.view(frontend)['step_id'], -1)
                self.clock.now += .01
                original_sync()

            frontend.controller.synchronize = inspect_device
            frontend.append_pcm(np.full(2760, .1, np.float32))
            result = frontend.advance()
            self.assertEqual([v['text'] for v in observations], ['', ''])
            view = self.view(frontend)
            self.assertEqual((view['text'], view['state_token']), ('international', '<|user_nonidle|>'))
            self.assertEqual(view['text_published_at'], view['state_published_at'])
            self.assertGreater(view['batch_published_at'], view['text_available_at'])
            self.assertGreaterEqual(view['batch_published_at'], result['lanes_completed_at'])
            self.assertFalse(hasattr(frontend.controller, 'stop_output'))

    def test_wait_batch_preserves_text_times_but_advances_state_and_progress(self):
        frontend = self.make(emissions=[[12, 2], None, None, None])
        frontend.append_pcm(np.full(5320, .1, np.float32))
        frontend.advance()
        first = self.view(frontend)
        self.clock.now += .05
        frontend.advance()
        second = self.view(frontend)
        for field in ('text', 'text_available_at', 'text_published_at', 'text_observed_until'):
            self.assertEqual(second[field], first[field])
        self.assertEqual(second['asr_processed_until'], 5120)
        self.assertGreater(second['batch_published_at'], first['batch_published_at'])
        self.assertGreater(second['asr_progress_available_at'], first['asr_progress_available_at'])
        self.assertEqual(second['completion_status'], 'none')

    def test_native_reset_preserves_unread_pcm_and_x2_text_across_cycles(self):
        frontend = self.make(predictions=[99, 3, 99, 6], emissions=[[12, 2], None, [13, 2], None])
        frontend.append_pcm(np.full(5320, .1, np.float32))
        first = frontend.advance()
        self.assertEqual(first['receipts']['controller']['generation_after'], 1)
        second = frontend.advance()
        self.assertEqual(second['receipts']['controller']['windows']['main']['spans'][-1]['start'], 1920)
        self.assertEqual(frontend.asr.groups.text, 'hello world again')
        self.assertEqual(frontend.barrier.step_id, 2)

    def test_producer_keeps_arriving_while_controller_waits(self):
        frontend = self.make()
        entered, proceed = threading.Event(), threading.Event()
        original = frontend.controller.step

        def delayed(*args):
            entered.set()
            if not proceed.wait(5):
                raise TimeoutError('Test controller was not released')
            return original(*args)

        frontend.controller.step = delayed
        frontend.append_pcm(np.full(2760, .1, np.float32))
        results, errors = [], []

        def run():
            try:
                results.append(frontend.advance())
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            frontend.append_pcm(np.full(2560, .1, np.float32))
            self.assertEqual(frontend.ledger.end, 5320)
            self.assertEqual(frontend.asr.frame_index, 0)
            with self.assertRaises(RuntimeError):
                frontend.advance()
        finally:
            proceed.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(frontend.asr.frame_index, 2)

    def test_eof_short_cycle_records_padding_without_fabricating_an_extra_frame(self):
        frontend = self.make(emissions=[[12, 2]])
        frontend.append_pcm(np.full(777, .1, np.float32))
        frontend.finish_input()
        result = frontend.advance()
        frames = result['receipts']['asr']['frames']
        self.assertEqual(len(frames), 1)
        self.assertTrue(result['receipts']['asr']['terminal'])
        self.assertEqual(frames[0]['asr_processed_until'], 777)
        self.assertEqual(frames[0]['asr_observed_until'], 777)
        self.assertEqual(frames[0]['input_spans'][-1]['reason'], 'eof_right_padding')
        self.assertIsNone(frontend.advance())
        self.assertEqual(frontend.asr.groups.text, 'hello world')

    def test_bounds_errors_cancel_both_lanes_and_preserve_progress(self):
        frontend = self.make()
        with self.assertRaises(BufferError):
            frontend.append_pcm(np.zeros(12801, np.float32))
        self.assertTrue(frontend.closed)
        self.assertTrue(frontend.controller.closed)
        self.assertTrue(frontend.asr.closed)
        self.assertEqual(frontend.diagnostics()['controller_processed_until'], 0)
        self.assertEqual(frontend.ledger.end, 0)
        with self.assertRaises(RuntimeError):
            frontend.advance()
        other = self.make()
        other.append_pcm(np.zeros(2760, np.float32))
        self.clock.now += 1
        with self.assertRaises(TimeoutError):
            other.advance()
        self.assertTrue(other.closed)
        large = self.make()
        with self.assertRaises(MemoryError):
            large.append_pcm(np.zeros(2**20, np.float32))

    def test_failure_after_one_lane_completes_never_releases_barrier(self):
        frontend = self.make(emissions=[[10, 11]])
        frontend.append_pcm(np.zeros(2760, np.float32))
        with self.assertRaises(StopIteration):
            frontend.advance()
        self.assertEqual(frontend.barrier.step_id, 0)
        diag = frontend.diagnostics()
        self.assertEqual(set(diag['pending_step']['receipts']), {'controller'})
        self.assertEqual(diag['asr']['open_group_tokens'], [10, 11])

    def test_model_pcm_growth_is_rejected_before_allocation(self):
        frontend = self.make()
        frontend.append_pcm(np.zeros(2760, np.float32))
        audio = np.zeros(800000, np.float32)
        frontend.controller.model.buffer_for_asr = frontend.controller._record(
            audio, [{'kind': 'synthetic', 'reason': 'bounded_test', 'samples': len(audio)}])
        with self.assertRaises(MemoryError):
            frontend.advance()
        self.assertTrue(frontend.closed)
        self.assertLessEqual(frontend.diagnostics()['pcm_bytes'], 4 * 2**20)
        self.assertEqual(frontend.barrier.step_id, 0)

    def test_close_or_overflow_during_inference_rejects_late_results(self):
        for reason in ('close', 'overflow'):
            frontend = self.make(('asr', 'controller'), emissions=[[12, 2], None])
            frontend.append_pcm(np.zeros(2760, np.float32))
            step = frontend.asr.engine.step

            def abort(audio, on_token):
                if reason == 'close':
                    frontend.close()
                else:
                    with self.assertRaises(BufferError):
                        frontend.append_pcm(np.zeros(11000, np.float32))
                return step(audio, on_token)

            frontend.asr.engine.step = abort
            with self.assertRaises(RuntimeError):
                frontend.advance()
            self.assertEqual(self.view(frontend)['step_id'], -1)
            self.assertEqual(frontend.barrier.step_id, 0)
            with self.assertRaises(RuntimeError):
                frontend.append_pcm(np.zeros(1, np.float32))

    def test_close_during_second_decode_preserves_previous_complete_snapshot(self):
        frontend = self.make(('asr', 'controller'), emissions=[[12, 2], None, [13, 2], None])
        frontend.append_pcm(np.full(5320, .1, np.float32))
        frontend.advance()
        first = self.view(frontend)
        original = frontend.asr.engine.step
        entered, proceed = threading.Event(), threading.Event()
        errors = []

        def delayed(audio, callback):
            entered.set()
            if not proceed.wait(5):
                raise TimeoutError('Decode was not released')
            return original(audio, callback)

        frontend.asr.engine.step = delayed

        def advance():
            try:
                frontend.advance()
            except RuntimeError as exc:
                errors.append(str(exc))

        worker = threading.Thread(target=advance)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            frontend.close()
            self.assertEqual(self.view(frontend)['status'], 'closed')
        finally:
            proceed.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.view(frontend)['text'], first['text'])
        self.assertEqual(self.view(frontend)['step_id'], first['step_id'])
        self.assertEqual(frontend.barrier.step_id, 1)

    def test_commit_failure_never_releases_or_changes_previous_observation(self):
        for kind in ('text', 'bytes', 'store'):
            frontend = self.make(emissions=[[12, 2], None, [13, 2], None])
            frontend.append_pcm(np.full(5320, .1, np.float32))
            frontend.advance()
            previous = self.view(frontend)
            if kind == 'text':
                frontend.context.max_chars = len(previous['text'])
            elif kind == 'bytes':
                frontend.context.max_snapshot_bytes = 512
            else:
                def fail(*args):
                    raise RuntimeError('Injected write failure')
                frontend.context.publish_joint_batch = fail
            with self.assertRaises(RuntimeError):
                frontend.advance()
            current = self.view(frontend)
            for field in ('step_id', 'text', 'state_token', 'batch_published_at'):
                self.assertEqual(current[field], previous[field])
            self.assertTrue(frontend.closed)
            self.assertTrue(frontend.asr.closed)
            self.assertEqual(frontend.barrier.step_id, 1)

    def test_next_model_batch_cannot_begin_until_commit_returns(self):
        frontend = self.make()
        frontend.append_pcm(np.zeros(5320, np.float32))
        publish = frontend.context.publish_joint_batch
        entered, proceed = threading.Event(), threading.Event()
        errors = []

        def delayed(batch):
            entered.set()
            if not proceed.wait(5):
                raise TimeoutError('Commit was not released')
            return publish(batch)

        frontend.context.publish_joint_batch = delayed

        def advance():
            try:
                frontend.advance()
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=advance)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(frontend.barrier.step_id, 0)
            self.assertEqual(frontend.asr.frame_index, 2)
            self.assertEqual(self.view(frontend)['step_id'], -1)
            with self.assertRaises(RuntimeError):
                frontend.advance()
        finally:
            proceed.set()
            worker.join(5)
        self.assertFalse(errors)
        self.assertFalse(worker.is_alive())
        frontend.advance()
        self.assertEqual(self.view(frontend)['step_id'], 1)

    def test_barrier_rejects_missing_duplicate_stale_and_cancelled_receipts(self):
        clock = Clock()
        barrier = StepBarrier(clock)
        ticket = barrier.begin(0, 2560)
        with self.assertRaises(RuntimeError):
            barrier.begin(2560, 5120)
        row = {'lane': 'asr', 'step_id': 0, 'completed_at': clock()}
        barrier.acknowledge(ticket, row)
        with self.assertRaises(RuntimeError):
            barrier.release({})
        with self.assertRaises(ValueError):
            barrier.acknowledge(ticket, row)
        barrier.acknowledge(ticket, dict(row, lane='controller'))
        barrier.release(dict(step_id=0, session_id='session', turn_id='turn',
                             status='open', batch_published_at=clock()))
        new_ticket = barrier.begin(2560, 5120)
        with self.assertRaises(RuntimeError):
            barrier.acknowledge(ticket, row)
        barrier.cancel()
        with self.assertRaises(RuntimeError):
            barrier.acknowledge(new_ticket, dict(row, step_id=1))

    def test_joint_context_rejects_malformed_receipts_without_half_writes(self):
        frontend = self.make(emissions=[[12, 2], [13, 2]])
        frontend.append_pcm(np.full(2760, .1, np.float32))
        batch = frontend.advance()
        mutations = [
            lambda b: b['receipts'].pop('controller'),
            lambda b: b['receipts']['asr']['frames'].pop(),
            lambda b: b['receipts']['asr']['frames'].append(b['receipts']['asr']['frames'][0]),
            lambda b: b['receipts']['controller'].update(session_id='other'),
            lambda b: b['receipts']['asr'].update(step_id=2),
            lambda b: b['receipts']['controller'].update(completed_at=99),
            lambda b: b['receipts']['controller'].pop('started_at'),
            lambda b: b['receipts']['controller'].update(started_at=float('nan')),
            lambda b: b['receipts']['asr']['frames'][0].update(started_at=101),
            lambda b: b['receipts']['asr']['frames'][1].pop('started_at'),
            lambda b: b['receipts']['controller'].update(generation_after=5),
            lambda b: b['receipts']['asr']['frames'][0].update(decoding=True),
            lambda b: b['receipts']['asr']['frames'][0].update(open_group_tokens=[10]),
            lambda b: b['receipts']['asr']['frames'][0].update(asr_processed_until=0),
            lambda b: b['receipts']['asr']['frames'][0].update(text='rewritten'),
            lambda b: b['staged']['progress'].__setitem__(0, {}),
            lambda b: b['staged']['text'].pop(),
            lambda b: b['staged'].update(state=None),
            lambda b: b.update(source_end=100),
            lambda b: b['receipts']['asr']['frames'][1].update(text_available_at=float('nan')),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                context = SharedContext(clock=self.clock)
                previous = context.open_user_turn('session', 'turn', 'x2_streaming_asr')
                candidate = deepcopy(batch)
                mutate(candidate)
                with self.assertRaises((ValueError, KeyError)):
                    context.publish_joint_batch(candidate)
                self.assertEqual(context.get_user_turn('session', 'turn'), previous)
        previous = self.view(frontend)
        with self.assertRaises(ValueError):
            frontend.context.publish_joint_batch(batch)
        with self.assertRaises(ValueError):
            frontend.context.publish_user_frame(previous)
        self.assertEqual(self.view(frontend), previous)

    def test_handoff_updates_merge_with_new_batch_and_reject_stale_writers(self):
        frontend = self.make(emissions=[[12, 2], None, [13, 2], None])
        frontend.append_pcm(np.full(5320, .1, np.float32))
        frontend.advance()
        context = frontend.context
        context.update_completion('session', 'turn', expected_step_id=0, expected_completion_id=None,
                                  expected_completion_status='none',
                                  fields={'completion_id': 'c1', 'completion_status': 'pending'})
        frontend.advance()
        current = self.view(frontend)
        self.assertEqual(current['completion_id'], 'c1')
        self.assertEqual(current['completion_status'], 'pending')
        with self.assertRaises(ValueError):
            context.update_completion('session', 'turn', expected_step_id=0, expected_completion_id='c1',
                                      expected_completion_status='pending', fields={'completion_status': 'ready'})
        context.update_completion('session', 'turn', expected_step_id=1, expected_completion_id='c1',
                                  expected_completion_status='pending', fields={'completion_status': 'cancelled'})
        with self.assertRaises(ValueError):
            context.update_completion('session', 'turn', expected_step_id=1, expected_completion_id='c1',
                                      expected_completion_status='pending', fields={'completion_status': 'ready'})
        self.assertEqual(self.view(frontend)['text'], 'hello world again')
        with self.assertRaises(ValueError):
            context.update_completion('session', 'turn', expected_step_id=1, expected_completion_id='c1',
                                      expected_completion_status='cancelled', fields={'text': 'stale'})
        frontend.close()
        with self.assertRaises(ValueError):
            context.update_completion('session', 'turn', expected_step_id=1, expected_completion_id='c1',
                                      expected_completion_status='cancelled', fields={'completion_status': 'ready'})

    def test_concurrent_readers_only_observe_complete_batches_and_receive_copies(self):
        frontend = self.make(emissions=[[13, 2], None] * 8)
        done, entered = threading.Event(), threading.Event()
        errors, observations = [], []

        def read():
            entered.set()
            try:
                while not done.is_set():
                    timed = frontend.context.get_user_turn('session', 'turn', with_timing=True)
                    view = timed['snapshot']
                    self.assertGreaterEqual(timed['read_seconds'], 0)
                    if view['step_id'] >= 0:
                        self.assertEqual(view['committed_groups'], view['step_id'] + 1)
                        self.assertEqual(view['text'], ' '.join(['again'] * view['committed_groups']))
                        self.assertEqual(view['asr_processed_until'], (view['step_id'] + 1) * 2560)
                        self.assertEqual(view['text_published_at'], view['state_published_at'])
                        observations.append(view)
                        view['controller_windows']['main']['spans'].clear()
            except Exception as exc:
                errors.append(exc)

        reader = threading.Thread(target=read)
        reader.start()
        try:
            self.assertTrue(entered.wait(5))
            frontend.append_pcm(np.full(2760, .1, np.float32))
            for index in range(8):
                if index:
                    frontend.append_pcm(np.full(2560, .1, np.float32))
                frontend.advance()
        finally:
            done.set()
            reader.join(5)
        self.assertFalse(reader.is_alive())
        self.assertFalse(errors)
        self.assertTrue(observations)
        self.assertTrue(self.view(frontend)['controller_windows']['main']['spans'])
        self.assertEqual(len(frontend.context.latest), 1)

    def test_eof_frame_counts_and_tail_coverage_remain_explicit(self):
        for length in (1, 777, 1280, 1281, 2559, 2560, 2761):
            with self.subTest(length=length):
                frontend = self.make()
                frontend.append_pcm(np.full(length, .1, np.float32))
                frontend.finish_input()
                while frontend.advance() is not None:
                    pass
                view = self.view(frontend)
                self.assertEqual(view['asr_processed_until'], length)
                self.assertTrue(view['terminal_batch'])
                self.assertEqual(view['partial_batch'], length % 2560 != 0)
                self.assertEqual(view['tail_status'], 'unknown')
                self.assertFalse(view['coverage_complete'])
                self.assertEqual(view['completion_status'], 'none')
                self.assertEqual(frontend.diagnostics()['unprocessed_real_samples']['asr'], 0)

    def test_external_close_and_delayed_callbacks_cannot_revive_a_turn(self):
        frontend = self.make()
        frontend.append_pcm(np.zeros(5320, np.float32))
        frontend.advance()
        row = deepcopy(frontend.last_step['staged']['state'])
        with self.assertRaises(RuntimeError):
            frontend._stage('state', row)
        frontend.context.close_user_turn('session', 'turn', 'external_close')
        with self.assertRaises(RuntimeError):
            frontend.advance()
        self.assertEqual(frontend.asr.frame_index, 2)
        self.assertEqual(self.view(frontend)['step_id'], 0)

    def test_pcm_rejects_implicit_conversion_and_eof_writes(self):
        ledger = PCMLedger()
        for invalid in (np.zeros(5, np.int16), np.zeros((2, 2), np.float32),
                        np.array([np.nan], np.float32), np.array([1.1], np.float32)):
            with self.assertRaises(ValueError):
                ledger.append(invalid)
        ledger.append(np.zeros(2560, np.float32))
        with self.assertRaises(BufferError):
            ledger.window(0, 2760)
        ledger.finish()
        with self.assertRaises(RuntimeError):
            ledger.append(np.zeros(1, np.float32))


if __name__ == '__main__':
    unittest.main()
