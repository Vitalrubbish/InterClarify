"""Distinguish raw logits from the processed scores used for greedy decoding."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).parents[1] / 'scripts/remote'))
from diagnose_kv_cache import processed_comparison, summarize_logits
import torch


class ProcessedScoreTests(unittest.TestCase):
    """Reproduce the observed ranking flip after the inherited repetition penalty."""

    def test_repetition_penalty_exposes_small_cache_difference(self):
        full = torch.full((3000,), -100.)
        full[40], full[2121] = 14.4375, 13.75
        cached = full.clone()
        cached[2121] = 13.8125
        tokenizer = SimpleNamespace(decode=lambda ids:str(ids))
        model = SimpleNamespace(model=SimpleNamespace(
            generation_config=SimpleNamespace(repetition_penalty=1.05),
            get_input_embeddings=lambda:SimpleNamespace(weight=torch.zeros(1))),tokenizer=tokenizer)
        self.assertTrue(summarize_logits(full,cached,tokenizer)['argmax_equal'])
        self.assertTrue(processed_comparison(model,[40,12],full,cached)['argmax_equal'])
        result = processed_comparison(model,[40,12],full,cached,repetition_penalty=1.05)
        self.assertFalse(result['argmax_equal'])
        self.assertEqual(result['full']['ids'][0],40)
        self.assertEqual(result['cached']['ids'][0],2121)
        self.assertLess(result['full']['top_margin'],1e-5)
        self.assertAlmostEqual(result['cached']['top_margin'],.0625,places=5)
