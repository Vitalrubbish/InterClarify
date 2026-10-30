"""Exercise transcript identity, partial windows and bounded request coalescing."""
import importlib.util
from pathlib import Path
import threading
import time
import unittest

SPEC = importlib.util.spec_from_file_location(
    'textturn_context', Path(__file__).parents[1] / 'scripts/runtime/textturn_context.py')
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


class TextTurnContextTests(unittest.TestCase):
    def snapshot(self, version=0, text='', **extra):
        return {'session_id': 's', 'turn_id': 't', 'source': 'nemotron', 'asr_generation': 'g',
                'version': version, 'asr_prefix_version': version, 'text': text,
                'status': 'open', 'received_at': time.monotonic(), **extra}

    def test_context_deduplicates_and_separates_close_from_eof(self):
        shared = context.SharedContext(max_updates=3)
        consumer = context.TranscriptConsumer('s')
        shared.publish_user_transcript(self.snapshot())
        consumer.consume(shared)
        shared.publish_user_transcript(self.snapshot(1, 'hello'))
        shared.publish_user_transcript(self.snapshot(1, 'hello'))
        self.assertEqual(len(consumer.consume(shared)), 1)
        self.assertEqual(shared.publish_user_transcript(self.snapshot())['status'], 'ignored_old_version')
        with self.assertRaises(ValueError):
            shared.publish_user_transcript(self.snapshot(2, 'rewritten'))
        shared.publish_user_transcript(self.snapshot(2, 'hello', status='closed', close_reason='runtime_turn_close'))
        consumer.consume(shared)
        self.assertEqual(consumer.turns['t']['text'], 'hello')
        self.assertEqual(consumer.consume(shared), [])
        with self.assertRaises(ValueError):
            shared.publish_user_transcript(self.snapshot(3, 'hello more'))

    def test_three_decode_steps_and_short_eof_window(self):
        assembler = context.ControlWindowAssembler(480)
        windows = []
        for index, text in enumerate(['a', 'a', 'ab', 'ab'], 1):
            value = assembler.push_step({'kind': 'decode_step', 'step_seq': index, 'text': text,
                'prefix_version': index, 'published_at': index * .16,
                'nominal_audio_start_ms': (index - 1) * 160, 'nominal_audio_end_ms': index * 160})
            if value:
                windows.append(value)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]['user_delta'], 'ab')
        tail = assembler.flush()
        self.assertEqual(tail['step_count'], 1)
        self.assertEqual(tail['observation'], '<|no-voice|>')
        self.assertTrue(tail['partial_window'])
        self.assertEqual(tail['nominal_end_ms'] - tail['nominal_start_ms'], 160)

    def test_one_pending_snapshot_merges_without_losing_text(self):
        entered, release = threading.Event(), threading.Event()
        seen = []

        def decide(window):
            seen.append(window['user_delta'])
            entered.set()
            if len(seen) == 1:
                release.wait(1)
            return 'keep'

        def window(index, before, text):
            now = time.monotonic()
            return {'first_step_seq': index * 3 - 2, 'last_step_seq': index * 3,
                    'nominal_start_ms': (index - 1) * 480, 'nominal_end_ms': index * 480,
                    'first_input_visible_at': now, 'input_ready_at': now, 'text': text,
                    'text_before_window': before, 'user_delta': text[len(before):],
                    'step_count': 3, 'merged_windows': 0}

        worker = context.LatestControlWorker(decide)
        worker.submit(window(1, '', 'a'))
        self.assertTrue(entered.wait(1))
        worker.submit(window(2, 'a', 'ab'))
        worker.submit(window(3, 'ab', 'abc'))
        release.set()
        results = worker.close(2)
        self.assertEqual(seen, ['a', 'bc'])
        self.assertEqual(worker.merged, 1)
        self.assertEqual(results[-1]['window']['step_count'], 6)

    def test_160ms_emits_one_complete_cycle_per_decode_step(self):
        assembler = context.ControlWindowAssembler()
        for index in range(1, 4):
            window = assembler.push_step({'kind': 'decode_step', 'step_seq': index, 'text': 'a',
                'prefix_version': 1, 'published_at': index*.16,
                'nominal_audio_start_ms': (index-1)*160, 'nominal_audio_end_ms': index*160})
            self.assertEqual(window['step_count'], 1)
            self.assertFalse(window['partial_window'])
            self.assertEqual(window['observation'], 'a' if index == 1 else '<|no-voice|>')
        self.assertIsNone(assembler.flush())


if __name__ == '__main__':
    unittest.main()
