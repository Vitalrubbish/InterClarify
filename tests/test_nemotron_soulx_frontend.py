"""Verify append-only source publication and token-revision boundaries on CPU."""
from copy import deepcopy
from pathlib import Path
import sys
import threading
from collections import deque
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from shared_context import SharedContext, FrontendConsumer
from nemotron_soulx_frontend import NemotronSoulXFrontend, token_patch, fresh_prefix


def frontend():
    value = NemotronSoulXFrontend.__new__(NemotronSoulXFrontend)
    value.context, value.publication_lock = SharedContext(), threading.RLock()
    value.session_id, value.turn_id = 's', 't'
    value.producer_seq = value.controller_generation = 0
    value.asr_generation, value.clock_id = 's:t:nemotron', 'cpu'
    value.on_commit, value.control = None, None
    value.native_generation, value.native_seq, value.native_text = None, 0, ''
    value.prefixes, value.closed = deque(maxlen=4096), False
    value.snapshot = value._event('user_transcript', source='nemotron', version=0, asr_version=0,
                                  text='', status='open')
    value._commit([value.snapshot])
    return value


def event(index, text, **extra):
    return {'generation': 'native-g', 'event_seq': index, 'kind': 'transcript',
            'text': text, 'consumed_samples': index * 2560, 'received_samples': index * 2560,
            'prefix_version': index, 'published_at': index * .16, 'eof_received': False, **extra}


class NemotronSoulXTests(unittest.TestCase):
    def test_word_internal_append_is_published_without_inserted_spaces(self):
        value = frontend()
        first, second = FrontendConsumer('s'), FrontendConsumer('s')
        value.accept_asr_event(event(1, 'inter'))
        first.consume(value.context)
        value.accept_asr_event(event(2, 'internet connection'))
        for consumer in (first, second):
            consumer.consume(value.context)
            self.assertEqual(consumer.turns['t']['text'], 'internet connection')
        self.assertEqual(value.prefixes[-1]['observed_until'], 5120)

    def test_rewrite_gap_generation_and_future_watermark_rejected(self):
        for bad in (event(2, 'changed'), event(3, 'hello more'),
                    event(2, 'hello more', generation='other'),
                    event(2, 'hello more', consumed_samples=10000)):
            with self.subTest(bad=bad):
                value = frontend()
                value.accept_asr_event(event(1, 'hello'))
                with self.assertRaises(ValueError):
                    value.accept_asr_event(bad)
                self.assertEqual(value.context.get_user_turn('s', 't')['transcript']['text'], 'hello')

    def test_eof_is_diagnostic_and_token_rewrite_has_explicit_common_prefix(self):
        value = frontend()
        value.accept_asr_event(event(1, 'hello'))
        value.accept_asr_event(event(2, 'hello world', eof_received=True))
        self.assertEqual(value.context.get_user_turn('s', 't')['transcript']['text'], 'hello')
        self.assertEqual(value.native_text, 'hello world')
        self.assertEqual(token_patch([1, 2, 3], [1, 7, 8]), 1)
        self.assertEqual(token_patch([1, 2], [1, 2, 3]), 2)
        self.assertFalse(fresh_prefix(True, {'text': 'hello'}, 5))
        self.assertFalse(fresh_prefix(False, {'text': 'hello more'}, 5))
        self.assertTrue(fresh_prefix(True, {'text': 'hello more'}, 5))

    def test_context_refuses_source_switch_and_native_rewrite(self):
        value = frontend()
        value.accept_asr_event(event(1, 'hello'))
        for source, text in (('nemotron', 'other'), ('sensevoice_small', 'hello more')):
            snapshot = value._event('user_transcript', source=source, text=text,
                                    version=2, asr_version=2, base_asr_version=1,
                                    replace_from=0, replacement=text, status='open')
            with self.assertRaises(ValueError):
                value.context.publish_user_transcript(snapshot)


if __name__ == '__main__':
    unittest.main()
