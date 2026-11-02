"""Exercise EOS publication, source identity, barriers and bounded lifecycle failures."""
from contextlib import nullcontext
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
        asr.step(self.ledger(), 0)
        self.assertEqual((text, progress), ([], []))
        with self.assertRaises(RuntimeError):
            asr.step(self.ledger(), 1)


class AudioTests(unittest.TestCase):
    def make(self, order=('controller', 'asr'), predictions=None, emissions=None, **kwargs):
        self.clock = Clock()
        controller = NativeSoulX(official_model(predictions or [99, 6] * 10),
                                 source_path=SOURCE, synchronize=lambda: None, clock=self.clock,
                                 on_state=kwargs.pop('on_state', None))
        self.addCleanup(controller.detach)
        asr = IndependentX2(FakeEngine(emissions or [None] * 20), clock=self.clock,
                            on_text=kwargs.pop('on_text', None), on_progress=kwargs.pop('on_progress', None))
        return DualAudioFrontend(controller, asr, clock=self.clock, order=order, **kwargs)

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

    def test_first_x2_group_publishes_before_second_frame_and_before_control(self):
        events = []
        frontend = self.make(('asr', 'controller'), emissions=[[10, 11, 2], None],
                             on_text=lambda row: events.append(('text', row['frame_index'])),
                             on_progress=lambda row: events.append(('progress', row['frame_index'])),
                             on_state=lambda row: events.append(('state', row['step_id'])))
        frontend.append_pcm(np.full(2760, .1, np.float32))
        frontend.advance()
        self.assertEqual(events, [('text', 0), ('progress', 0), ('progress', 1), ('state', 0)])

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
            events = []
            frontend = self.make(('asr', 'controller'), emissions=[[12, 2], None],
                                 on_text=events.append, on_state=events.append, on_progress=events.append)
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
            self.assertEqual(events, [])
            self.assertEqual(frontend.barrier.step_id, 0)
            with self.assertRaises(RuntimeError):
                frontend.append_pcm(np.zeros(1, np.float32))

    def test_close_waits_for_an_active_short_callback_and_suppresses_the_rest(self):
        entered, proceed, close_started, close_finished = [threading.Event() for _ in range(4)]
        events, errors = [], []

        def receive(row):
            events.append('text')
            entered.set()
            if not proceed.wait(5):
                raise TimeoutError('Test callback was not released')

        frontend = self.make(('asr', 'controller'), emissions=[[12, 2], None], on_text=receive,
                             on_progress=lambda row: events.append('progress'),
                             on_state=lambda row: events.append('state'))
        frontend.append_pcm(np.zeros(2760, np.float32))

        def advance():
            try:
                frontend.advance()
            except RuntimeError as exc:
                errors.append(str(exc))

        def close():
            close_started.set()
            frontend.close()
            close_finished.set()

        worker, closer = threading.Thread(target=advance), threading.Thread(target=close)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            closer.start()
            self.assertTrue(close_started.wait(5))
            self.assertFalse(close_finished.wait(.02))
        finally:
            proceed.set()
            worker.join(5)
            if closer.ident is not None:
                closer.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertTrue(close_finished.is_set())
        self.assertEqual(events, ['text'])
        self.assertEqual(len(errors), 1)

    def test_barrier_rejects_missing_duplicate_stale_and_cancelled_receipts(self):
        clock = Clock()
        barrier = StepBarrier(clock)
        ticket = barrier.begin(0, 2560)
        with self.assertRaises(RuntimeError):
            barrier.begin(2560, 5120)
        row = {'lane': 'asr', 'step_id': 0, 'completed_at': clock()}
        barrier.acknowledge(ticket, row)
        with self.assertRaises(RuntimeError):
            barrier.release()
        with self.assertRaises(ValueError):
            barrier.acknowledge(ticket, row)
        barrier.acknowledge(ticket, dict(row, lane='controller'))
        barrier.release()
        new_ticket = barrier.begin(2560, 5120)
        with self.assertRaises(RuntimeError):
            barrier.acknowledge(ticket, row)
        barrier.cancel()
        with self.assertRaises(RuntimeError):
            barrier.acknowledge(new_ticket, dict(row, step_id=1))

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
