"""Exercise actual teacher inputs and blocking decoder publication boundaries."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/remote'))
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from nemotron_teacher_worker import BarrierSession, reorder_sample
from nemotron_teacher_frontend import TeacherCursor, NemotronTeacherFrontend, official_control_text
from nemotron_teacher_fdb import AudioProgressPairing, run_case
from shared_context import STATE_IDS


class BarrierTests(unittest.TestCase):
    def test_streamer_precedes_generator_advance(self):
        source = '''def sample(self, streamer):
    while self.more:
        values = self._update_model_kwargs_for_generation()
        if streamer is not None:
            streamer.put('last token')
        self.more = False
'''
        events = []
        namespace = {}
        exec(compile(reorder_sample(source), '<test>', 'exec'), namespace)
        model = SimpleNamespace(more=True, _update_model_kwargs_for_generation=lambda: events.append('feature resume'))
        namespace['sample'](model, SimpleNamespace(put=lambda token: events.append(token)))
        self.assertEqual(events, ['last token', 'feature resume'])
        with self.assertRaises(ValueError):
            reorder_sample('def sample():\n    pass\n')

    def test_completion_blocks_and_cancel_wakes(self):
        advanced = threading.Event()
        class Engine:
            supports_decode_steps = True
            def run(self, source, emit, complete):
                emit('inter', [1])
                complete({'step_seq': 1, 'decode_completed_at': time.monotonic()})
                advanced.set()
                complete({'step_seq': 2, 'decode_completed_at': time.monotonic()})
        session = BarrierSession(Engine())
        deadline = time.monotonic() + 1
        while session.step_seq != 1 and time.monotonic() < deadline:
            time.sleep(.001)
        self.assertEqual(session.read_steps()['steps'][0]['text'], 'inter')
        self.assertFalse(advanced.is_set())
        with self.assertRaises(ValueError):
            session.release(2, time.monotonic())
        session.release(1, time.monotonic())
        self.assertTrue(advanced.wait(1))
        with self.assertRaises(ValueError):
            session.release(1, time.monotonic())
        session.source.cancel()
        session.worker.join(1)
        self.assertFalse(session.worker.is_alive())
        self.assertIsNone(session.error)

    def test_cursor_empty_increment_and_prefix_integrity(self):
        cursor = TeacherCursor()
        self.assertEqual(cursor.advance({'step_seq': 1, 'text': 'inter'}), 'inter')
        self.assertEqual(cursor.advance({'step_seq': 2, 'text': 'inter'}), '')
        self.assertEqual(cursor.advance({'step_seq': 3, 'text': 'internet'}), 'net')
        for step in ({'step_seq': 4, 'text': 'other'}, {'step_seq': 5, 'text': 'internet'}):
            with self.assertRaises(ValueError):
                cursor.advance(step)


def remove_leading_backchannel(text):
    return text.lstrip('嗯啊 .,!?')


def zh_remove_punc(text):
    return re.sub(r'[^A-Za-z0-9 \u4e00-\u9fff]', '', text)


def zh_norm(text):
    return text


def split_cn_en(text):
    return re.findall(r'[\u4e00-\u9fff]|[A-Za-z]+|[0-9]+', text)


def check_en(text):
    return text.isascii()


class FakeModel:
    def __init__(self, predictions, gates=()):
        import torch
        self.calls, self.histories, self.predictions = [], [], iter(predictions)
        self.gates = iter(gates)
        class Tokenizer:
            all_special_ids = list(STATE_IDS.values()) + [151674]
            def encode(self, text, **kwargs):
                return [STATE_IDS[text]] if text in STATE_IDS else [1001] if text == 'inter' else [1002] if text == 'internet' else [ord(c) for c in text]
            def decode(self, ids, **kwargs):
                return next((s for s, i in STATE_IDS.items() if ids == [i]), ''.join('inter' if i == 1001 else 'internet' if i == 1002 else chr(i) for i in ids))
        self.model = SimpleNamespace(tokenizer=Tokenizer(), asr_eos_token_id=151674, llm=self.forward)
        self.device = 'cpu'
        self.text_embeds = torch.tensor([[-1.]])
        self.audio_eos_token = torch.tensor([151674])
        self.audio_eos_embeds = self.embed_tokens_func(self.audio_eos_token)
        self.config = SimpleNamespace(infer_config=SimpleNamespace(max_mistake_num=3, far_field_threshold=.001))
    def embed_tokens_func(self, ids):
        return ids.float().reshape(-1, 1)
    def _audio_to_tokens(self, *args):
        return [-2, -3]
    def _tokens_to_embeds(self, ids):
        import torch
        return torch.tensor(ids).float().reshape(-1, 1)
    def get_rms(self, chunk):
        return .1
    def forward(self, inputs_embeds, past_key_values, use_cache):
        import torch
        values = inputs_embeds.flatten().tolist()
        self.calls.append(values)
        cache = past_key_values if past_key_values is not None else []
        cache.extend(values)
        self.histories.append(list(cache))
        logits = torch.zeros(1, 1, 151682)
        logits[0, 0, next(self.predictions) if values[-1] == 151674 else next(self.gates, 65)] = 10
        logits[0, 0, STATE_IDS['<|user_incomplete|>']] += 1
        return SimpleNamespace(logits=logits, past_key_values=cache)


class TeacherInputTests(unittest.TestCase):
    def make(self, predictions, gates=(), **kwargs):
        source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with patch('nemotron_teacher_frontend.UPSTREAM_SHA256', source_hash), patch('nemotron_teacher_frontend.verify_tools'):
            return NemotronTeacherFrontend(FakeModel(predictions, gates), 'test', **kwargs)

    def step(self, frontend, seq, text):
        return frontend.process_step({'step_seq': seq, 'text': text}, None, None, None, seq * 2560, seq * 2560)

    def test_exact_teacher_delta_and_one_state_feedback_across_reset(self):
        nonidle, complete = STATE_IDS['<|user_nonidle|>'], STATE_IDS['<|user_complete|>']
        front = self.make([complete, nonidle, nonidle])
        first = self.step(front, 1, 'Hello,')
        self.assertEqual(front.generation, 1)
        second = self.step(front, 2, 'Hello, world!')
        third = self.step(front, 3, 'Hello, world!')
        calls = front.model.calls
        self.assertEqual(calls[0], [-1, -2, -3])
        self.assertEqual(calls[1], list(map(ord, 'Hello')) + [151674])
        self.assertEqual(calls[2], [complete, -2, -3])
        self.assertEqual(calls[3], list(map(ord, ' world')) + [151674])
        self.assertEqual(calls[4:], [[nonidle, -2, -3], [151674]])
        self.assertEqual(first['control_text'], 'Hello')
        self.assertEqual(second['text'], 'Hello, world!')
        self.assertEqual(third['delta_text'], '')
        self.assertEqual(front.close()['text'], 'Hello, world!')

    def test_unknown_token_is_never_fed_back(self):
        front = self.make([66, STATE_IDS['<|user_nonidle|>']])
        first = self.step(front, 1, '')
        self.assertFalse(first['state_accepted'])
        self.step(front, 2, 'a')
        self.assertEqual(front.model.calls[2], [-2, -3])
        self.assertNotIn(65, front.model.kv if hasattr(front.model, 'kv') else front.kv)
        self.assertNotIn(66, front.kv)

    def test_closed_gate_retains_updates_until_open_and_eof(self):
        front = self.make([STATE_IDS['<|user_nonidle|>']] * 4, gates=[151674, 151674, 65, 151674])
        one = self.step(front, 1, 'Hello,')
        two = self.step(front, 2, 'Hello, world!')
        self.assertEqual(front.teacher_ids, [])
        three = self.step(front, 3, 'Hello, world!')
        self.assertEqual(three['delta_text'], 'Hello world')
        four = self.step(front, 4, 'Hello, world! Again.')
        self.assertEqual(four['control_consumption'], 'closed_pending')
        self.assertEqual(four['pending_token_range'], [11, 17])
        self.assertEqual(two['text'], 'Hello, world!')
        self.assertEqual(one['teacher_source_status'], 'completed_new')
        calls = len(front.model.calls)
        self.assertEqual(front.close()['text'], 'Hello, world! Again.')
        self.assertEqual(len(front.model.calls), calls)

    def test_word_extension_revises_mutable_cache_and_preserves_real_state(self):
        complete, nonidle = STATE_IDS['<|user_complete|>'], STATE_IDS['<|user_nonidle|>']
        front = self.make([complete, nonidle])
        self.step(front, 1, 'inter')
        saved = list(front.checkpoint['kv'])
        self.assertEqual(saved, [-1, -2, -3])
        second = self.step(front, 2, 'internet')
        self.assertEqual(second['cache_revision']['replay_mode'], 'recent_checkpoint')
        self.assertEqual(front.checkpoint['kv'], saved)
        self.assertEqual(front.kv, [-1, -2, -3, 1002, 151674, complete, -2, -3, 151674])
        self.assertEqual(front.teacher_ids, [1002])
        self.assertNotIn(65, front.kv)
        self.assertEqual(front.context.get_user_turn('test', 'user-1')['text'], 'internet')

    def test_older_revision_uses_bounded_rebuild(self):
        nonidle = STATE_IDS['<|user_nonidle|>']
        front = self.make([nonidle] * 3)
        with patch('nemotron_teacher_frontend.official_control_text', side_effect=['ab', 'ab c', 'ax c']):
            self.step(front, 1, '1')
            self.step(front, 2, '12')
            third = self.step(front, 3, '123')
        self.assertEqual(third['cache_revision']['replay_mode'], 'bounded_rebuild')
        self.assertEqual(front.teacher_ids, list(map(ord, 'ax c')))
        self.assertEqual(front.kv, [-1, -2, -3, 97, 120, 151674, nonidle, -2, -3, 32, 99, 151674,
                                   nonidle, -2, -3, 151674])
        self.assertEqual(third['cache_revision']['revision_from_step'], 1)

    def test_closed_gate_defers_consumed_token_revision(self):
        nonidle = STATE_IDS['<|user_nonidle|>']
        front = self.make([nonidle] * 3, gates=[65, 151674, 65])
        self.step(front, 1, 'inter')
        closed = self.step(front, 2, 'internet')
        self.assertEqual(front.teacher_ids, [1001])
        self.assertEqual(closed['pending_token_range'], [0, 1])
        opened = self.step(front, 3, 'internet')
        self.assertEqual(opened['raw_delta_text'], '')
        self.assertEqual(opened['delta_text'], 'internet')
        self.assertEqual(opened['cache_revision']['replay_mode'], 'recent_checkpoint')
        self.assertNotIn(1001, front.kv)
        self.assertEqual(front.kv.count(1002), 1)
        self.assertEqual(front.kv.count(nonidle), 2)

    def test_normalized_prefix_contraction_replays_without_duplicate_text(self):
        nonidle = STATE_IDS['<|user_nonidle|>']
        front = self.make([nonidle] * 3)
        with patch('nemotron_teacher_frontend.official_control_text', side_effect=['ab', 'a', '']):
            self.step(front, 1, '1')
            second = self.step(front, 2, '12')
            third = self.step(front, 3, '123')
        self.assertEqual(second['consumed_token_ids'], [97])
        self.assertEqual(third['consumed_token_ids'], [])
        self.assertNotIn(97, front.kv)
        self.assertNotIn(98, front.kv)
        self.assertEqual(front.kv.count(151674), 3)

    def test_limits_fail_without_publishing_new_state(self):
        nonidle = STATE_IDS['<|user_nonidle|>']
        front = self.make([nonidle], max_tokens=3)
        with self.assertRaisesRegex(RuntimeError, 'token limit'):
            self.step(front, 1, '')
        for limits in ({'max_rebuilds': 0}, {'max_replay_tokens': 1}):
            front = self.make([nonidle, nonidle], **limits)
            self.step(front, 1, 'inter')
            with self.assertRaisesRegex(RuntimeError, 'replay limit'):
                self.step(front, 2, 'internet')

    def test_official_formatter_calls_frozen_pipeline(self):
        front = self.make([])
        with patch(__name__ + '.remove_leading_backchannel', return_value=' ab! ') as leading, \
             patch(__name__ + '.zh_remove_punc', return_value='ab') as punctuation, \
             patch(__name__ + '.zh_norm', return_value='AB') as norm, \
             patch(__name__ + '.split_cn_en', return_value=['AB', '中']) as split:
            self.assertEqual(official_control_text(front.model, 'raw'), 'AB 中')
            leading.assert_called_once_with('raw')
            punctuation.assert_called_once_with('ab!')
            norm.assert_called_once_with('ab')
            split.assert_called_once_with('AB')

    def test_empty_nonidle_rule_ablation_preserves_transition_rule(self):
        nonidle, idle = STATE_IDS['<|user_nonidle|>'], STATE_IDS['<|user_idle|>']
        for enabled in (True, False):
            front = self.make([nonidle] * 3 + [idle], empty_nonidle_rule=enabled)
            frames = [self.step(front, seq, '') for seq in range(1, 5)]
            self.assertEqual(frames[2]['adjustment'], 'empty_nonidle_count' if enabled else None)
            if not enabled:
                self.assertEqual(frames[3]['adjustment'], 'nonidle_to_idle')


class AudioPairingTests(unittest.TestCase):
    @staticmethod
    def native(seq, end, next_end, text=''):
        return dict(step_seq=seq, feature_end_sample=end, next_feature_end_sample=next_end,
                    consumed_samples=end, received_samples=end, eof_received=False, text=text)

    def test_short_startup_then_first_sufficient_window(self):
        pairing = AudioProgressPairing()
        cursor = TeacherCursor()
        first = self.native(1, 1480, 4144, 'inter')
        self.assertEqual(pairing.accept(first, 2560), 'startup')
        self.assertEqual((pairing.native_seq, pairing.teacher_seq), (1, 0))
        second = self.native(2, 4144, 6704, 'internet')
        self.assertEqual(pairing.accept(second, 2560), 'context')
        self.assertEqual(cursor.advance(dict(second, step_seq=pairing.teacher_seq)), 'internet')
        third = self.native(3, 6704, 9264, 'internet works')
        self.assertEqual(pairing.accept(third, 5120), 'context')
        self.assertEqual(cursor.advance(dict(third, step_seq=pairing.teacher_seq)), ' works')
        self.assertEqual((pairing.native_seq, pairing.teacher_seq), (3, 2))

    def test_reject_missing_coverage_skipped_steps_and_drain(self):
        for second in (self.native(2, 2500, 5060), self.native(3, 4144, 6704),
                       dict(self.native(2, 4144, 6704), eof_received=True),
                       self.native(2, 4304, 6864)):
            pairing = AudioProgressPairing()
            pairing.accept(self.native(1, 1480, 4144), 2560)
            with self.subTest(second=second), self.assertRaises(ValueError):
                pairing.accept(second, 2560)

    def test_realtime_eof_and_startup_text_with_actual_barrier(self):
        import json
        import numpy as np
        class Engine:
            supports_decode_steps = True
            def run(self, source, emit, complete):
                seq, start, size = 1, 0, 1480
                while True:
                    audio = source.read(start, size)
                    if audio is None:
                        return
                    end = start + size
                    emit('inter' if seq == 1 else 'internet' if not source.eof else 'internet tail', [seq])
                    complete(dict(step_seq=seq, feature_start_sample=start, feature_end_sample=end,
                                  next_feature_end_sample=4144 if seq == 1 else end + 2560,
                                  consumed_samples=source.consumed, received_samples=source.received,
                                  eof_received=source.eof, decode_started_at=time.monotonic(),
                                  decode_completed_at=time.monotonic()))
                    start, size, seq = (1184 if seq == 1 else start + 2560), 2960, seq + 1
        session = BarrierSession(Engine())
        releases = []
        def fake_rpc(path, operation, **payload):
            if operation == 'create':
                return {'session_id': session.id}
            if operation == 'push':
                import base64
                session.source.append(base64.b64decode(payload.get('audio', '')), eof=payload.get('eof', False))
                return session.snapshot()
            if operation == 'poll':
                return session.read_steps(payload['after'])
            if operation == 'release':
                releases.append((payload['step_seq'], payload.get('publication_kind', 'context')))
                return session.release(payload['step_seq'], payload['published_at'], payload.get('publication_kind', 'context'))
            if operation == 'close':
                session.source.cancel()
                session.worker.join(1)
                return {'ok': True}
            raise AssertionError(operation)
        model = FakeModel([STATE_IDS['<|user_nonidle|>']] * 4)
        model.config.infer_config.input = SimpleNamespace(audio_back_size=0, audio_ahead_size=640)
        source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temporary, patch('nemotron_teacher_fdb.rpc', fake_rpc), \
                patch('nemotron_teacher_frontend.UPSTREAM_SHA256', source_hash), patch('nemotron_teacher_frontend.verify_tools'):
            record = run_case(model, np.ones(8000, np.float32) * .1, 'eof', None, Path(temporary))
            frames = [json.loads(line) for line in (Path(temporary) / 'eof.frames.jsonl').read_text().splitlines()]
        self.assertTrue(record['passed'])
        self.assertEqual(record['frames'], 2)
        self.assertEqual(record['online_text'], 'internet')
        self.assertEqual(record['drained_text'], 'internet tail')
        self.assertEqual(releases, [(1, 'startup'), (2, 'context'), (3, 'context')])
        self.assertEqual(frames[0]['delta_text'], 'internet')
        self.assertEqual(frames[1]['delta_text'], '')
        self.assertEqual(frames[0]['native_step']['step_seq'], 2)
        self.assertEqual(frames[0]['teacher_step_seq'], 1)
        self.assertEqual(frames[0]['asr_observation_ahead_ms'], 99)
        self.assertFalse(session.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
