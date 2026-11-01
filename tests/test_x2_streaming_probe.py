"""Check X2 probe contracts without loading the 4B model."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/remote'))
from x2_streaming_probe import (
    WAIT_TOKEN_ID,
    WORD_TOKEN_ID,
    audit_cumulative_text,
    distribution,
    evaluate_gate,
    group_audit,
    parse_groups,
    select_case,
)
from x2_streaming_probe import continuous_audio  # noqa: F401  (import contract only)


class FakeTokenizer:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def decode(self, ids, **kwargs):
        return ''.join(self.mapping.get(i, '') for i in ids)


class GroupTests(unittest.TestCase):
    def test_groups_close_only_at_next_word_or_wait(self):
        tokens = [WORD_TOKEN_ID, 100, 101, WAIT_TOKEN_ID,
                  WORD_TOKEN_ID, 102]
        emit = [index * 80. for index in range(len(tokens))]
        parsed = parse_groups(tokens, emit)
        self.assertEqual(parsed['word_markers'], 2)
        self.assertEqual(parsed['wait_markers'], 1)
        self.assertEqual(len(parsed['groups']), 1)
        self.assertEqual(parsed['groups'][0]['token_ids'], [100, 101])
        self.assertEqual(parsed['groups'][0]['close_reason'], 'wait')
        self.assertEqual(parsed['unclosed_tail']['token_ids'], [102])
        self.assertEqual(parsed['unbound_tokens'], [])

    def test_group_prefix_violation_is_reported(self):
        tokenizer = FakeTokenizer({100: 'a', 101: 'b'})
        tokens = [WORD_TOKEN_ID, 100, WAIT_TOKEN_ID, 101]
        emit = [index * 80. for index in range(len(tokens))]
        cumulative, rewrites = audit_cumulative_text(tokenizer, tokens)
        self.assertEqual(cumulative, ['', 'a', 'a', 'ab'])
        self.assertEqual(rewrites, [])
        parsed = group_audit(tokenizer, tokens, emit, cumulative)
        self.assertEqual(parsed['group_prefix_violations'], [])
        self.assertEqual(parsed['groups'][0]['close_delay_frames'], 1)

    def test_rewrite_is_reported(self):
        class Rewriting(FakeTokenizer):
            def decode(self, ids, **kwargs):
                if ids == [100, 101]:
                    return 'b'
                return super().decode(ids, **kwargs)
        tokenizer = FakeTokenizer({100: 'a', 101: 'b'})
        tokenizer.decode = Rewriting({100: 'a', 101: 'b'}).decode
        cumulative, rewrites = audit_cumulative_text(tokenizer, [100, 101])
        self.assertEqual(cumulative, ['a', 'b'])
        self.assertEqual(len(rewrites), 1)
        self.assertEqual(rewrites[0]['frame'], 1)

    def test_unbound_text_never_enters_a_group(self):
        parsed = parse_groups([100, WAIT_TOKEN_ID], [0., 80.])
        self.assertEqual(parsed['groups'], [])
        self.assertEqual(parsed['unbound_tokens'], [{'frame': 0, 'token_id': 100}])


class MetricTests(unittest.TestCase):
    def test_distribution_uses_interpolated_percentiles(self):
        result = distribution([0., 100.])
        self.assertEqual(result['p50'], 50.)
        self.assertEqual(result['p95'], 95.)
        self.assertEqual(result['max'], 100.)
        self.assertIsNone(distribution([])['p50'])

    def test_gate_requires_every_threshold(self):
        config = {'gate': {'x2_rtf_max': .6, 'backlog_p95_ms_max': 320,
                           'continuous_drift_ms_max': 160, 'peak_gpu_mib_max': 12288}}
        cases = [
            {'case_id': 'a', 'passed': True, 'x2_rtf': .4, 'backlog_ms': {'p95': 200.}},
            {'case_id': 'continuous_60s', 'passed': True, 'x2_rtf': .5,
             'backlog_ms': {'p95': 250.}, 'backlog_drift_ms': 100.},
        ]
        self.assertTrue(evaluate_gate(cases, config, 9000., 2)['passed'])
        cases[1]['backlog_drift_ms'] = 161.
        self.assertFalse(evaluate_gate(cases, config, 9000., 2)['passed'])
        cases[1]['backlog_drift_ms'] = 100.
        self.assertFalse(evaluate_gate(cases, config, 13000., 2)['passed'])

    def test_case_selection(self):
        samples = [{'case_id': 'short', 'duration_seconds': 1.},
                   {'case_id': 'long', 'duration_seconds': 2.}]
        self.assertEqual(select_case(samples, longest=True)['case_id'], 'long')
        self.assertEqual(select_case(samples, 'short')['case_id'], 'short')
        with self.assertRaises(ValueError):
            select_case(samples, 'missing')


if __name__ == '__main__':
    unittest.main()
