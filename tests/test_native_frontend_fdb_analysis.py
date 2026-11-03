"""Keep native timing, joint publication and fixed quality denominators separate."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/analysis'))
from analyze_native_frontend_fdb import compare_inputs, score_case, score_times, task_summary


class AnalysisTests(unittest.TestCase):
    def test_delayed_publication_does_not_change_native_early_completion(self):
        sample = {'task': 'smooth_turn_taking', 'annotation': [{'timestamp': [1., 1.2]}]}
        event = {'accepted': True, 'token': '<|user_complete|>',
                 'times': {'main': .8, 'observed': .84, 'available': .99, 'published': 1.1, 'read': 1.11}}
        self.assertEqual(score_times(sample, [event], 'main')['over_160ms_early'], 1)
        self.assertEqual(score_times(sample, [event], 'available')['early_complete'], 1)
        self.assertEqual(score_times(sample, [event], 'published')['after_boundary_complete'], 1)
        self.assertEqual(score_times(sample, [event], 'published')['early_complete'], 0)

    def test_pause_is_half_open_and_interruption_uses_only_accepted_nonidle(self):
        sample = {'task': 'pause_handling', 'annotation': [{'timestamp': [1., 2.]}]}
        events = [{'accepted': True, 'token': '<|user_complete|>', 'times': {'main': at}} for at in [1., 2.]]
        self.assertEqual(score_times(sample, events, 'main')['pause_intervals'][0]['complete_events'], 1)
        sample['task'] = 'user_interruption'
        events += [{'accepted': False, 'token': '<|user_nonidle|>', 'times': {'main': 1.1}},
                   {'accepted': True, 'token': '<|user_nonidle|>', 'times': {'main': 1.25}}]
        result = score_times(sample, events, 'main')
        self.assertTrue(result['nonidle_detected'])
        self.assertEqual(result['nonidle_delay_ms'], 250.)
        self.assertEqual(result['after_boundary_complete'], 1)

    def row(self, step, text, token):
        state = {'state_processed_until': (step + 1) * 2560, 'state_observed_until': (step + 1) * 2560 + 640,
                 'state_available_at': 100.2 + step * .16, 'state_token': token, 'raw_token': token,
                 'state_accepted': True, 'rule_applied': False, 'control_text': text, 'control_delta': text}
        controller = {'state': state, 'completed_at': 100.25 + step * .16,
            'windows': {name: {'sha256': 'pcm'} for name in ('main', 'lookback', 'lookahead')},
            'events': [{'kind': 'stage', 'name': '_audio_to_tokens', 'audio_token_ids': [1, 2]}]}
        return {'step_id': step, 'receipts': {'controller': controller,
            'asr': {'completed_at': 100.24 + step * .16, 'frames': [{'decision': 33, 'text': text, 'frame_index': step * 2}]}},
            'released_at': 100.3 + step * .16, 'batch_published_at': 100.3 + step * .16,
            'read_at': 100.31 + step * .16, 'snapshot': {'text': text, 'text_observed_until': (step + 1) * 2560}}

    def test_complete_tail_and_cross_group_continuation_are_reported_without_rewrite(self):
        rows = [self.row(0, 'hello', '<|user_complete|>'), self.row(1, 'helloWorld', '<|user_idle|>')]
        sample = {'case_id': 'one', 'task': 'smooth_turn_taking', 'annotation': [{'timestamp': [1., 1.2]}], 'reference': 'hello world'}
        result = score_case(sample, {'started_at': 100., 'passed': True, 'online_text': 'helloWorld'}, rows, True)
        self.assertEqual(result['completion_snapshots'][0]['text'], 'hello')
        self.assertEqual(result['completion_snapshots'][0]['later_closed_text'], 'World')
        self.assertEqual(result['cross_group_continuation_candidates'][0]['delta_prefix'], 'World')
        self.assertFalse(result['drain_performed'])

    def test_input_matching_detects_state_and_text_differences(self):
        left = self.row(0, 'hello', '<|user_complete|>')
        right = deepcopy(left)
        right['receipts']['controller']['state']['control_text'] = 'changed'
        result = compare_inputs([left], [right])
        self.assertEqual(result['matched_windows'], 1)
        self.assertIn('control_text', result['differences'][0]['changed'])
        right['receipts']['controller']['windows']['main']['sha256'] = 'different'
        result = compare_inputs([left], [right])
        self.assertEqual(result['matched_windows'], 0)
        self.assertEqual(result['unmatched_dual'], 1)

    def test_zero_frame_failures_remain_in_fixed_scoring_denominator(self):
        sample = {'case_id': 'empty', 'task': 'user_interruption', 'annotation': [{'timestamp': [1., 2.]}], 'reference': 'hello world'}
        result = score_case(sample, {'passed': False}, [], True)
        summary = task_summary([result])['user_interruption']
        self.assertEqual(summary['fixed_cases'], 1)
        self.assertEqual(summary['coordinates']['main']['scored_cases'], 1)
        self.assertEqual(summary['coordinates']['main']['cases_with_nonidle_detected'], 0)
        self.assertEqual(summary['online_word_errors']['reference_words'], 2)
        self.assertEqual(summary['online_word_errors']['wer'], 1.)


if __name__ == '__main__':
    unittest.main()
