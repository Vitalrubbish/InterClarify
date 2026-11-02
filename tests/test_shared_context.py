"""Check latest-only corrections, snapshot isolation and turn boundaries."""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from shared_context import SharedContext, STATE_IDS


def frame(text='hello', end=2560, token='<|user_nonidle|>'):
    return {'session_id': 's', 'turn_id': 't', 'source': 'sensevoice_small',
            'text': text, 'state_token': token, 'state_token_id': STATE_IDS[token],
            'state_accepted': True, 'processed_until': end, 'audio_observed_until': end + 640,
            'assembly_status': 'assembled', 'coverage_complete': True, 'status': 'open'}


class SharedContextTests(unittest.TestCase):
    def test_service_fields_default_and_validate_completion_semantics(self):
        context = SharedContext()
        opened = context.open_user_turn('s', 't')
        self.assertEqual((opened['service_state'], opened['service_completion_source'],
                          opened['speech_detected'], opened['service_text']),
                         (None, None, False, ''))
        self.assertFalse(context.publish_user_frame(frame())['speech_detected'])
        fallback = context.publish_user_frame(dict(
            frame(end=5120, token='<|user_idle|>'), service_state='speak',
            service_completion_source='wait_fallback', service_text='diagnostic'))
        self.assertEqual((fallback['service_completion_source'], fallback['service_text']),
                         ('wait_fallback', 'diagnostic'))
        for bad in ({'service_state': 'speak', 'service_completion_source': 'model_complete'},
                    {'service_state': 'speak', 'service_completion_source': 'model_complete',
                     'speech_detected': True},
                    {'service_state': 'idle', 'service_completion_source': 'wait_fallback'},
                    {'service_state': 'speak', 'speech_detected': 'yes'},
                    {'service_state': 'unknown'},
                    {'state_accepted': False, 'rejection_reason': 'no_speech'},
                    {'service_state': 'speak', 'service_completion_source': 'wait_fallback',
                     'state_token': '<|user_complete|>'}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    context.publish_user_frame(dict(frame(end=7680), **bad))
        self.assertEqual(context.get_user_turn('s', 't')['processed_until'], 5120)

    def test_explicit_nemotron_source_is_fixed_for_turn(self):
        context = SharedContext()
        context.open_user_turn('s', 't', source='nemotron')
        context.publish_user_frame(dict(frame(), source='nemotron'))
        with self.assertRaises(ValueError):
            context.publish_user_frame(frame(end=5120))
        self.assertEqual(context.get_user_turn('s', 't')['source'], 'nemotron')

    def test_publication_mode_is_fixed_and_legacy_teacher_requires_explicit_open(self):
        context = SharedContext()
        opened = context.open_user_turn('s', 't', 'x2_streaming_asr')
        self.assertEqual(opened['publication_mode'], 'joint')
        with self.assertRaises(ValueError):
            context.publish_user_frame(dict(frame(), source='x2_streaming_asr', publication_mode='legacy_frame'))
        self.assertEqual(context.get_user_turn('s', 't'), opened)
        context.open_user_turn('s', 'legacy', 'x2_streaming_asr', publication_mode='legacy_frame')
        result = context.publish_user_frame(dict(frame(), turn_id='legacy', source='x2_streaming_asr',
                                                  publication_mode='joint'))
        self.assertEqual(result['publication_mode'], 'legacy_frame')

    def test_close_capacity_failure_still_fences_late_writes(self):
        context = SharedContext()
        context.open_user_turn('s', 't')
        previous = context.publish_user_frame(frame())
        context.max_snapshot_bytes = 1
        with self.assertRaises(RuntimeError):
            context.close_user_turn('s', 't', 'close_capacity_test')
        context.max_snapshot_bytes = 256 * 1024
        with self.assertRaises(ValueError):
            context.publish_user_frame(frame(end=5120))
        self.assertEqual(context.get_user_turn('s', 't'), previous)
        context.release_closed_turn('s', 't')

    def test_correction_deletion_and_reader_isolation_without_history(self):
        context = SharedContext()
        context.open_user_turn('s', 't')
        first = context.publish_user_frame(frame('book Beijing tomorrow'))
        context.publish_user_frame(frame('book Shanghai', 5120, '<|user_complete|>'))
        first['text'] = 'mutated reader'
        current = context.get_user_turn('s', 't')
        self.assertEqual((current['text'], current['state_token']), ('book Shanghai', '<|user_complete|>'))
        self.assertEqual(len(context.latest), 1)
        self.assertFalse(hasattr(context, 'events'))
        self.assertFalse({'version', 'asr_version', 'event_seq'} & current.keys())
        current['text'] = 'mutated again'
        self.assertEqual(context.get_user_turn('s', 't')['text'], 'book Shanghai')

    def test_invalid_frame_and_closed_turn_do_not_overwrite_current(self):
        context = SharedContext(max_turns=1, max_chars=12)
        context.open_user_turn('s', 't')
        expected = context.publish_user_frame(frame())
        for bad in (frame(end=2560), frame(end=1), {**frame(end=5120), 'state_token_id': 0},
                    {**frame(end=5120), 'source': 'nemotron'}, frame('x' * 13, 5120)):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, RuntimeError)):
                    context.publish_user_frame(bad)
                self.assertEqual(context.get_user_turn('s', 't'), expected)
        with self.assertRaises(RuntimeError):
            context.open_user_turn('s', 'other')
        context.close_user_turn('s', 't', 'eof')
        self.assertEqual(context.get_user_turn('s', 't')['text'], 'hello')
        with self.assertRaises(ValueError):
            context.publish_user_frame(frame('late', 5120))
        context.release_closed_turn('s', 't')
        context.open_user_turn('s', 'new')
        self.assertEqual(len(context.latest), 1)

    def test_parallel_reads_never_mix_text_and_state(self):
        context = SharedContext()
        context.open_user_turn('s', 't')
        started, finished = threading.Event(), threading.Event()
        errors = []
        def write():
            started.wait()
            try:
                for index in range(1, 301):
                    token = '<|user_nonidle|>' if index % 2 else '<|user_complete|>'
                    context.publish_user_frame(frame(token, index * 2560, token))
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        thread = threading.Thread(target=write)
        thread.start()
        started.set()
        while not finished.is_set():
            view = context.get_user_turn('s', 't')
            if view['state_token'] is not None:
                self.assertEqual(view['text'], view['state_token'])
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(context.get_user_turn('s', 't')['processed_until'], 300 * 2560)


if __name__ == '__main__':
    unittest.main()
