"""Compare real upstream control methods with read-only native instrumentation."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import time
import types
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
from dual_audio import PCMLedger
from native_soulx import NativeSoulX

SOURCE = ROOT / 'third_party/soulx-duplug/service/model.py'
TOKENS = {3: '<|user_complete|>', 4: '<|user_incomplete|>', 5: '<|user_nonidle|>',
          6: '<|user_idle|>', 7: '<|user_backchannel|>'}


def official_model(predictions, texts=()):
    """Use upstream methods with tiny deterministic CPU dependencies, no weights."""
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TurnModel')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name != '__init__']
    module = ast.Module(body=methods, type_ignores=[])
    namespace = dict(np=np, torch=torch, time=time, math=__import__('math'),
                     remove_leading_backchannel=lambda s: s,
                     split_cn_en=lambda s: s.split(), zh_norm=lambda s: s,
                     zh_remove_punc=lambda s: s, check_en=lambda s: True)
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), namespace)
    model_type = type('TurnModel', (), {n.name: namespace[n.name] for n in methods})
    model = model_type()
    model.trace, scripted, words = [], iter(predictions), iter(texts)
    model.config = types.SimpleNamespace(
        infer_config=AttrDict(input=types.SimpleNamespace(sample_rate=16000, chunk_size=2560,
                   audio_back_size=15360, audio_ahead_size=640),
                   asr=types.SimpleNamespace(model_name='sensevoice', language='en'),
                   far_field_threshold=.02, max_wait_num=2, max_mistake_num=3),
        model_config=types.SimpleNamespace(user_complete_token_id=3, user_incomplete_token_id=4))
    model.device, model.sampling_rate, model.developer_mode = 'cpu', 16000, False
    model.text_embeds = model.audio_eos_embeds = torch.zeros((1, 2))
    model.non_idle_embeds = torch.ones((1, 2))
    model.action_speak_embeds = torch.full((1, 2), 3.)
    model.action_wait_embeds = torch.full((1, 2), 4.)
    model.embed_tokens_func = lambda ids: ids.float().reshape(-1, 1).repeat(1, 2)

    def lm(**kwargs):
        pred = next(scripted)
        if isinstance(pred, tuple):
            pred, choose_complete = pred
        else:
            choose_complete = True
        model.trace.append(('llm', kwargs['inputs_embeds'].clone(), kwargs['past_key_values']))
        logits = torch.full((1, 1, 100), -10.)
        logits[0, 0, 3], logits[0, 0, 4] = (1., 0.) if choose_complete else (0., 1.)
        logits[0, 0, pred] = 10.
        return types.SimpleNamespace(logits=logits, past_key_values=len(model.trace))

    def audio_tokens(back, chunk, ahead):
        model.trace.append(('audio', back.copy(), chunk.copy(), ahead.copy()))
        return [1, 2]

    def recognize(audio, rate):
        model.trace.append(('recognize', audio.copy(), rate))
        return next(words)

    model._audio_to_tokens = audio_tokens
    model._tokens_to_embeds = lambda ids: torch.ones((2, 2))
    tokenizer = types.SimpleNamespace(encode=lambda s, **kw: [ord(c) % 90 for c in s],
                                     decode=lambda v, **kw: TOKENS[int(v)])
    model.model = types.SimpleNamespace(llm=lm, asr_eos_token_id=99, tokenizer=tokenizer)
    model.cascade_asr = types.SimpleNamespace(recognize=recognize)
    model.reset()
    return model


class AttrDict(dict):
    def __getattr__(self, name):
        return self[name]


class NativeTests(unittest.TestCase):
    def ledger(self, count=12000, amplitude=.1):
        ledger = PCMLedger()
        ledger.append(np.full(count, amplitude, np.float32))
        return ledger

    def attach(self, model, **kwargs):
        value = NativeSoulX(model, synchronize=lambda: None, source_path=SOURCE, **kwargs)
        self.addCleanup(value.detach)
        return value

    def assert_trace_equal(self, left, right):
        self.assertEqual(len(left), len(right))
        for a, b in zip(left, right):
            self.assertEqual(a[0], b[0])
            for x, y in zip(a[1:], b[1:]):
                if isinstance(x, torch.Tensor):
                    self.assertTrue(torch.equal(x, y))
                elif isinstance(x, np.ndarray):
                    np.testing.assert_array_equal(x, y)
                else:
                    self.assertEqual(x, y)

    def test_uninstrumented_reference_matches_inputs_feedback_correction_and_reset(self):
        predictions = [0, 5, 0, 0, (6, False), 99, 3, 99, 6]
        np.random.seed(42)
        reference = official_model(predictions, ['hello', 'world', 'whole turn'])
        initial_rng = np.random.get_state()
        np.random.seed(42)
        wrapped = official_model(predictions, ['hello', 'world', 'whole turn'])
        wrapper = self.attach(wrapped)
        ledger = self.ledger()
        results, expected, cursors = [], [], [0, 2560, 5120, 7040]
        # Compare the same PCM/config/seed; reset's pending lookahead comes from the source ledger.
        for index, cursor in enumerate(cursors):
            audio, _ = ledger.window(cursor, cursor + 2560)
            np.random.set_state(initial_rng)
            native_result = reference.process(audio)
            next_rng = np.random.get_state()
            np.random.set_state(initial_rng)
            result = wrapper.step(ledger, index)
            initial_rng = next_rng
            expected.append(native_result)
            results.append(result)
            self.assertEqual(result['native_result'], native_result)
            for name in ('buffer', 'buffer_for_asr', 'cascade_buffer'):
                np.testing.assert_array_equal(getattr(reference, name), getattr(wrapped, name))
            self.assert_trace_equal(reference.trace, wrapped.trace)
        self.assertEqual(results[1]['state']['raw_token'], '<|user_idle|>')
        self.assertEqual(results[1]['state']['state_token'], '<|user_incomplete|>')
        self.assertTrue(results[1]['state']['rule_applied'])
        self.assertEqual(results[2]['service_completion_source'], 'model_complete')
        self.assertEqual(results[2]['events'][-1]['resume_from'], 7040)
        self.assertEqual(results[3]['windows']['main']['spans'][-1]['start'], 7040)
        self.assertEqual(wrapper.generation, 1)
        self.assertEqual(results[0]['windows']['main']['spans'][0]['samples'], 640)
        self.assertEqual(results[0]['state']['state_observed_until'], 2560)

    def test_nonidle_is_only_staged_and_has_no_output_hook(self):
        model = official_model([0, 5, 99, 5, 99, 5], ['hello'])
        order = []
        wrapper = self.attach(model, session_id='s', on_state=lambda _: order.append('state'))
        for step in range(3):
            wrapper.step(self.ledger(), step)
        self.assertEqual(order, ['state'] * 3)
        self.assertFalse(hasattr(wrapper, 'active_output'))
        self.assertFalse(hasattr(wrapper, 'stop_output'))

    def test_far_field_complete_rejection_and_service_fallback_are_separate(self):
        for token in (5, 3):
            wrapper = self.attach(official_model([99, token]))
            result = wrapper.step(self.ledger(amplitude=0), 0)
            self.assertFalse(result['state']['state_accepted'])
            self.assertEqual(result['service_state'], 'idle')
            self.assertIsNone(result['service_completion_source'])
            self.assertEqual(result['generation_after'], 1)
        wrapper = self.attach(official_model([99, 5, 99, 4, 99, 6, 99, 6], ['whole turn']))
        rows = [wrapper.step(self.ledger(), i) for i in range(4)]
        self.assertEqual(rows[-1]['state']['state_token'], '<|user_idle|>')
        self.assertEqual(rows[-1]['service_state'], 'speak')
        self.assertEqual(rows[-1]['service_completion_source'], 'wait_fallback')
        self.assertEqual(rows[-1]['service_text'], 'whole turn')
        self.assertNotIn('text', rows[-1]['state'])

    def test_cancel_rejects_callbacks_and_calls_without_destroying_diagnostics(self):
        calls = []
        wrapper = self.attach(official_model([99, 6]), on_state=calls.append)
        wrapper.cancel()
        with self.assertRaises(RuntimeError):
            wrapper.step(self.ledger(), 0)
        self.assertEqual(calls, [])

    def test_reset_never_restores_old_internal_buffer(self):
        wrapper = self.attach(official_model([99, 3, 99, 6]))
        wrapper.step(self.ledger(), 0)
        self.assertEqual((wrapper.processed_until, wrapper.submitted_until), (1920, 1920))
        self.assertTrue(all(s['kind'] == 'synthetic' for s in wrapper._spans(wrapper.model.buffer)))
        next_step = wrapper.step(self.ledger(), 1)
        self.assertEqual(next_step['windows']['main']['spans'][-1],
                         {'kind': 'real', 'start': 1920, 'end': 3840, 'samples': 1920})


if __name__ == '__main__':
    unittest.main()
