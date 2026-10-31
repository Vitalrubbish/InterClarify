"""Exercise independent computation, real coverage pairing and hard failure bounds."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/remote'))
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/analysis'))
from compare_dual_asr import audit_case
from dual_asr_frontend import PairedPublisher
from dual_asr_worker import UnreadAudioBuffer, IndependentSession
from dual_asr_fdb import run_case
from shared_context import SharedContext, STATE_IDS
from test_soulx_frontend import protocol_frontend, run_frame


def state(seq, observed=None, token='<|user_nonidle|>'):
    now = time.monotonic()
    return dict(session_id='s', turn_id='user-1', status='open', source='sensevoice_small',
                text='SenseVoice only', control_text='control only', state_token=token,
                state_token_id=STATE_IDS[token], raw_token=token, raw_token_id=STATE_IDS[token],
                state_accepted=True, rejection_reason=None, processed_until=seq * 2560,
                audio_observed_until=observed or seq * 2560 + 640,
                controller_started_at=now, controller_completed_at=now, state_resolved_at=now,
                coverage_complete=True, assembly_status='assembled', controller_generation=0)


def step(seq, text=''):
    end = 1480 if seq == 1 else 4144 + (seq - 2) * 2560
    now = time.monotonic()
    return dict(step_seq=seq, feature_start_sample=0 if seq == 1 else end - 2960,
                feature_end_sample=end, next_feature_end_sample=4144 if seq == 1 else end + 2560,
                consumed_samples=end, received_samples=end, text=text,
                decode_started_at=now, decode_completed_at=now, eof_received=False)


class PairingTests(unittest.TestCase):
    def make(self, **kwargs):
        context = SharedContext()
        context.open_user_turn('s', 'user-1', 'nemotron')
        return PairedPublisher(context, 's', **kwargs)

    def test_both_completion_orders_use_same_frozen_pair(self):
        for first in ('state', 'step'):
            with self.subTest(first=first):
                pub = self.make()
                pub.submit_step(step(1, 'startup'))
                if first == 'state':
                    pub.submit_state(state(1))
                else:
                    pub.submit_step(step(2, 'original'))
                self.assertEqual(pub.publish_ready(), [])
                if first == 'state':
                    pub.submit_step(step(2, 'original'))
                else:
                    pub.submit_state(state(1))
                pub.submit_step(step(3, 'later full text'))
                frames = pub.publish_ready()
                self.assertEqual(len(frames), 1)
                self.assertEqual(frames[0]['text'], 'original')
                self.assertEqual(frames[0]['native_step']['step_seq'], 2)
                self.assertEqual(frames[0]['control_text'], 'control only')
                self.assertEqual(frames[0]['audio_observed_until'], 4144)
                self.assertEqual(frames[0]['soulx_audio_observed_until'], 3200)
                self.assertGreaterEqual(frames[0]['published_at'], frames[0]['state_resolved_at'])
                self.assertGreaterEqual(frames[0]['published_at'], frames[0]['native_step']['decode_completed_at'])

    def test_real_lookahead_requires_later_step_instead_of_equal_step_number(self):
        pub = self.make()
        for n in range(1, 3):
            pub.submit_step(step(n, str(n)))
        pub.submit_state(state(1, observed=5000))
        self.assertEqual(pub.publish_ready(), [])
        pub.submit_step(step(3, 'actual coverage'))
        self.assertEqual(pub.publish_ready()[0]['text'], 'actual coverage')

    def test_official_short_first_main_keeps_real_sample_axis(self):
        pub = self.make()
        inputs = [dict(state(n), processed_until=n * 2560 - 640,
                       audio_observed_until=n * 2560, delta_text='') for n in (1, 2)]
        native = [step(n, 'body') for n in (1, 2, 3)]
        for value in inputs:
            pub.submit_state(value)
        for value in native:
            pub.submit_step(value)
        frames = pub.publish_ready()
        self.assertEqual([f['processed_until'] for f in frames], [1920, 4480])
        source = [dict(v, audit_kind='frame_source') for v in inputs]
        self.assertEqual(audit_case(frames, source, native)['audited_frames'], 2)
        frames[0]['text'] = 'wrong snapshot'
        with self.assertRaisesRegex(AssertionError, 'Published text'):
            audit_case(frames, source, native)
        frames[0]['text'] = 'body'
        frames[0]['native_step'] = native[2]
        with self.assertRaisesRegex(AssertionError, 'first sufficient'):
            audit_case(frames, source, native)

    def test_unchanged_text_is_completion_and_does_not_skip_intermediate_states(self):
        pub = self.make()
        for n in range(1, 5):
            pub.submit_step(step(n, 'same'))
        for n in range(1, 4):
            pub.submit_state(state(n))
        frames = pub.publish_ready()
        self.assertEqual([f['processed_until'] for f in frames], [2560, 5120, 7680])
        self.assertEqual([f['native_step']['step_seq'] for f in frames], [2, 3, 4])
        self.assertEqual([f['raw_delta_text'] for f in frames], ['same', '', ''])
        self.assertEqual(pub.publish_ready(), [])
        self.assertEqual(len(pub.context.latest), 1)

    def test_inputs_and_consumer_snapshots_are_independent_copies(self):
        pub = self.make()
        original = state(1)
        pub.submit_state(original)
        original['state_token'] = 'corrupted'
        for n in (1, 2):
            pub.submit_step(step(n, 'body'))
        frame = pub.publish_ready()[0]
        frame['text'] = 'changed'
        self.assertEqual(pub.context.get_user_turn('s', 'user-1')['text'], 'body')

    def test_eof_insufficient_and_complete_never_forces_publication(self):
        pub = self.make()
        pub.submit_state(state(1, token='<|user_complete|>'))
        pub.submit_step(step(1, 'tail not ready'))
        self.assertEqual(pub.publish_ready(), [])
        self.assertEqual(len(pub.diagnostics()['unpublished_states']), 1)
        pub.close()
        current = pub.context.get_user_turn('s', 'user-1')
        self.assertEqual(current['text'], '')
        self.assertEqual(current['processed_until'], 0)
        self.assertEqual(pub.diagnostics()['unpublished_states'], [])
        for submit, value in ((pub.submit_state, state(2)), (pub.submit_step, step(2))):
            with self.assertRaises(ValueError):
                submit(value)

    def test_full_real_window_completed_after_eof_can_pair(self):
        pub = self.make()
        pub.submit_state(state(1))
        pub.submit_step(step(1))
        pub.submit_step(dict(step(2, 'last full window'), eof_received=True))
        self.assertEqual(pub.publish_ready()[0]['text'], 'last full window')

    def test_bad_order_coverage_and_missing_window_fail(self):
        for bad in (dict(step(1), consumed_samples=1400), dict(step(1), received_samples=1000),
                    dict(step(1), decode_completed_at=0), step(2)):
            pub = self.make()
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pub.submit_step(bad)
        pub = self.make()
        pub.submit_step(step(1))
        with self.assertRaises(ValueError):
            pub.submit_step(dict(step(2), feature_end_sample=4304, consumed_samples=4304, received_samples=4304))
        pub.submit_state(state(1))
        for bad in (state(1), state(3)):
            with self.assertRaises(ValueError):
                pub.submit_state(bad)

    def test_queue_count_byte_span_and_text_limits_are_visible(self):
        pub = self.make(max_states=1)
        pub.submit_state(state(1))
        with self.assertRaisesRegex(RuntimeError, 'queue hard limit'):
            pub.submit_state(state(2))
        self.assertEqual(len(pub.diagnostics()['unpublished_states']), 1)
        pub = self.make(max_bytes=100)
        with self.assertRaisesRegex(RuntimeError, 'queue hard limit'):
            pub.submit_state(state(1))
        pub = self.make()
        for n in range(1, 6):
            pub.submit_state(state(n))
        with self.assertRaisesRegex(RuntimeError, '800ms'):
            pub.submit_state(state(6))
        pub = self.make(max_steps=1)
        pub.submit_step(step(1))
        with self.assertRaisesRegex(RuntimeError, 'queue hard limit'):
            pub.submit_step(step(2))
        pub = self.make()
        with self.assertRaisesRegex(RuntimeError, 'character limit'):
            pub.submit_step(step(1, 'x' * 65537))

    def test_context_commit_does_not_hold_producer_queue_lock(self):
        entered, release = threading.Event(), threading.Event()
        def commit(frame):
            entered.set()
            release.wait(1)
        pub = self.make(on_commit=commit)
        pub.submit_state(state(1))
        for n in (1, 2):
            pub.submit_step(step(n))
        worker = threading.Thread(target=pub.publish_ready)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            pub.submit_state(state(2))
            pub.submit_step(step(3))
            self.assertEqual(pub.state_end, 5120)
            with self.assertRaises(RuntimeError):
                pub.publish_ready()
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())


class NativeTests(unittest.TestCase):
    def test_retained_history_is_not_unread_pcm_and_eof_does_not_pad(self):
        source = UnreadAudioBuffer()
        source.append(bytes(8000))
        self.assertEqual(len(source.read(0, 3000)), 3000)
        source.append(bytes(22000))
        self.assertEqual(source.metrics()['unread_samples'], 12000)
        self.assertGreater(source.metrics()['retained_pcm_bytes'], 12800 * 4)
        with self.assertRaisesRegex(RuntimeError, '800ms'):
            source.append(bytes(2000))
        source.append(b'', eof=True)
        self.assertIsNone(source.read(14000, 2000))
        self.assertEqual(source.received, 15000)
        self.assertEqual(source.drain, 0)

    def test_cancel_wakes_native_read(self):
        source = UnreadAudioBuffer()
        result = []
        def read():
            try:
                source.read(0, 1480)
            except InterruptedError:
                result.append('cancelled')
        worker = threading.Thread(target=read)
        worker.start()
        source.cancel()
        worker.join(1)
        self.assertEqual(result, ['cancelled'])

    def test_decoder_advances_without_context_or_release(self):
        advanced = threading.Event()
        class Engine:
            supports_decode_steps = True
            def run(self, source, emit, complete):
                for n in (1, 2, 3):
                    emit('x' * n, [n])
                    complete(step(n))
                advanced.set()
        session = IndependentSession(Engine())
        self.assertTrue(advanced.wait(1))
        session.worker.join(1)
        self.assertIsNone(session.error)
        self.assertEqual([v['text'] for v in session.read_steps(0)['steps']], ['x', 'xx', 'xxx'])
        self.assertEqual(session.read_steps(2)['steps'][0]['text'], 'xxx')
        with self.assertRaises(ValueError):
            session.read_steps(1)

    def test_native_uncollected_queue_fails_instead_of_overwriting(self):
        class Engine:
            supports_decode_steps = True
            def run(self, source, emit, complete):
                for n in range(1, 18):
                    complete(step(n))
        session = IndependentSession(Engine())
        session.worker.join(1)
        self.assertIn('queue hard limit', session.error)
        self.assertEqual(len(session.steps), 16)


class NativeControllerTests(unittest.TestCase):
    def test_native_reset_and_immediate_nonidle_precede_pairing(self):
        front = protocol_frontend()
        front.turn_id = 'user-1'
        front.context = SharedContext()
        front.context.open_user_turn('s', 'user-1', 'nemotron')
        pub = PairedPublisher(front.context, 's')
        front.frame_sink = pub.submit_state
        stopped = []
        front.active_output = lambda: {'output_id': 'o', 'phase': 'playing'}
        front.stop_output = lambda *args: stopped.append('immediate')
        front._instrumented_state = lambda *args: front.observe_state('<|user_nonidle|>', '')
        run_frame(front, 0)
        self.assertEqual(stopped, ['immediate'])
        self.assertEqual(front.context.get_user_turn('s', 'user-1')['state_token'], None)
        front.model.buffer = front._record_array(np.zeros(640, np.float32),
            [{'kind': 'real', 'start': 5120, 'end': 5760, 'samples': 640}])
        resets = []
        def reset():
            resets.append('official')
            for name in ('buffer', 'buffer_for_asr', 'cascade_buffer'):
                setattr(front.model, name, np.zeros(640, np.float32))
        front._original = {'reset': reset}
        def complete(*args):
            front.observe_state('<|user_complete|>', '')
            front._reset_controller()
        front._instrumented_state = complete
        run_frame(front, 1, '<|user_complete|>')
        self.assertEqual(resets, ['official'])
        self.assertEqual(front.controller_generation, 1)
        self.assertEqual(front._spans(front.model.buffer)[0]['start'], 5120)
        for n in (1, 2, 3):
            pub.submit_step(step(n, 'RNNT only'))
        frames = pub.publish_ready()
        self.assertEqual([f['controller_generation'] for f in frames], [0, 0])
        self.assertEqual(frames[-1]['state_token'], '<|user_complete|>')
        self.assertEqual(frames[-1]['text'], 'RNNT only')

    def test_realtime_replay_keeps_eof_unpaired_state_and_closes_both_workers(self):
        class Engine:
            supports_decode_steps = True
            def run(self, source, emit, complete):
                seq = 1
                while True:
                    native = step(seq)
                    chunk = source.read(native['feature_start_sample'],
                                        native['feature_end_sample'] - native['feature_start_sample'])
                    if chunk is None:
                        return
                    emit('body' if seq < 3 else 'body tail', [seq])
                    native.update(received_samples=source.received, consumed_samples=source.consumed,
                                  eof_received=source.eof, decode_completed_at=time.monotonic())
                    complete(native)
                    seq += 1
        session = IndependentSession(Engine())
        operations, seen_audio = [], []
        def fake_rpc(path, operation, **payload):
            operations.append(operation)
            if operation == 'create':
                return {'session_id': session.id}
            if operation == 'push':
                import base64
                session.source.append(base64.b64decode(payload.get('audio', '')), eof=payload.get('eof', False))
                return session.snapshot()
            if operation == 'poll':
                return session.read_steps(payload['after'])
            if operation == 'close':
                session.source.cancel()
                session.worker.join(1)
                return {'ok': True}
            raise AssertionError(operation)
        def make_front(model, publisher, **kwargs):
            front = protocol_frontend()
            front.context = publisher.context
            front.session_id, front.turn_id = 's', 'user-1'
            front.context.open_user_turn('s', 'user-1', 'nemotron')
            front.input_end = 0
            front.audit = kwargs['audit']
            front.frame_sink = publisher.submit_state
            front._instrumented_state = lambda *args: front.observe_state('<|user_complete|>', '')
            def feed(packet):
                seen_audio.append(packet.copy())
                front.input_end += len(packet)
                while front.input_end >= front.processed_until + 3200:
                    run_frame(front, front.processed_until // 2560, '<|user_complete|>')
            front.feed_audio = feed
            front.detach = lambda **kwargs: None
            return front
        class Model:
            def reset(self):
                pass
        with tempfile.TemporaryDirectory() as temporary, patch('dual_asr_fdb.rpc', fake_rpc):
            output = Path(temporary)
            audio = np.ones(8320, np.float32) * .1
            result = run_case(Model(), audio, 's', None, output, frontend_factory=make_front)
            frames = [json.loads(line) for line in (output / 's.frames.jsonl').read_text().splitlines()]
            pending = json.loads((output / 's.pending.json').read_text())
        self.assertTrue(result['passed'], result.get('traceback'))
        self.assertEqual(result['frames'], 2)
        self.assertEqual(result['unpublished_states'], 1)
        self.assertEqual(result['online_text'], 'body tail')
        self.assertEqual(pending['unpublished_states'][0]['processed_until'], 7680)
        self.assertEqual([f['native_step']['step_seq'] for f in frames], [2, 3])
        self.assertEqual(len(np.concatenate(seen_audio)), 8320)
        self.assertNotIn('release', operations)
        self.assertEqual(operations.count('close'), 1)
        self.assertFalse(session.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
