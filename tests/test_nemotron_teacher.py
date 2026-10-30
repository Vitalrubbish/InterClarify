"""Exercise actual teacher inputs and blocking decoder publication boundaries."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/remote'))
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from nemotron_teacher_worker import BarrierSession, reorder_sample
from nemotron_teacher_frontend import TeacherCursor, NemotronTeacherFrontend
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


class FakeModel:
    def __init__(self, predictions):
        import torch
        self.calls, self.predictions = [], iter(predictions)
        class Tokenizer:
            all_special_ids = list(STATE_IDS.values()) + [151679]
            def encode(self, text, **kwargs):
                return [STATE_IDS[text]] if text in STATE_IDS else [ord(c) for c in text]
            def decode(self, ids, **kwargs):
                return next((s for s, i in STATE_IDS.items() if ids == [i]), ''.join(chr(i) for i in ids))
        self.model = SimpleNamespace(tokenizer=Tokenizer(), asr_eos_token_id=151679, llm=self.forward)
        self.device = 'cpu'
        self.text_embeds = torch.tensor([[-1.]])
        self.audio_eos_token = torch.tensor([151679])
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
        self.calls.append(inputs_embeds.flatten().tolist())
        logits = torch.zeros(1, 1, 151682)
        logits[0, 0, next(self.predictions)] = 10
        logits[0, 0, STATE_IDS['<|user_incomplete|>']] += 1
        return SimpleNamespace(logits=logits, past_key_values=object())


class TeacherInputTests(unittest.TestCase):
    def make(self, predictions, **kwargs):
        source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with patch('nemotron_teacher_frontend.UPSTREAM_SHA256', source_hash):
            return NemotronTeacherFrontend(FakeModel(predictions), 'test', **kwargs)

    def step(self, frontend, seq, text):
        return frontend.process_step({'step_seq': seq, 'text': text}, None, None, None, seq * 2560, seq * 2560)

    def test_exact_teacher_delta_and_one_state_feedback_across_reset(self):
        nonidle, complete = STATE_IDS['<|user_nonidle|>'], STATE_IDS['<|user_complete|>']
        front = self.make([complete, nonidle, nonidle])
        self.step(front, 1, 'inter')
        self.assertEqual(front.generation, 1)
        kv = front.kv
        self.step(front, 2, 'internet')
        self.assertIsNot(front.kv, kv)
        self.step(front, 3, 'internet')
        calls = front.model.calls
        self.assertEqual(calls[0], [-1, -2, -3] + list(map(ord, 'inter')) + [151679])
        self.assertEqual(calls[1], [complete, -2, -3] + list(map(ord, 'net')) + [151679])
        self.assertEqual(calls[2], [nonidle, -2, -3, 151679])
        self.assertEqual(front.close()['text'], 'internet')

    def test_unknown_token_is_never_fed_back(self):
        front = self.make([65, STATE_IDS['<|user_nonidle|>']])
        first = self.step(front, 1, '')
        self.assertFalse(first['state_accepted'])
        self.step(front, 2, 'a')
        self.assertEqual(front.model.calls[1], [-2, -3, ord('a'), 151679])

    def test_empty_nonidle_rule_ablation_preserves_transition_rule(self):
        nonidle, idle = STATE_IDS['<|user_nonidle|>'], STATE_IDS['<|user_idle|>']
        for enabled in (True, False):
            front = self.make([nonidle] * 3 + [idle], empty_nonidle_rule=enabled)
            frames = [self.step(front, seq, '') for seq in range(1, 5)]
            self.assertEqual(frames[2]['adjustment'], 'empty_nonidle_count' if enabled else None)
            if not enabled:
                self.assertEqual(frames[3]['adjustment'], 'nonidle_to_idle')


if __name__ == '__main__':
    unittest.main()
