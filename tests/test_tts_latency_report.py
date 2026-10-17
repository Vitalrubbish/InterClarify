"""Check scientific denominators and single-variable screen configuration."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/remote'))
import tts_latency_experiments as experiment
import tts_latency_report as report


class ExperimentContractTests(unittest.TestCase):
    def test_candidates_change_one_independent_variable(self):
        values = {arm['name']: arm for arm in experiment.arms()}
        for arm in values.values():
            if not arm['control']:
                continue
            base = values[arm['control']]
            changed = [key for key in ('batch', 'early', 'tokens', 'wait_ms') if arm[key] != base[key]]
            self.assertEqual(len(changed), 0 if arm['name'] == 'control_end' else 1)
        self.assertEqual(sum(len(arm['modes']) * 3 * 3 for arm in values.values()), 117)

    def test_combination_is_an_explicit_separate_suite(self):
        values = experiment.arms('combination')
        self.assertEqual([v['name'] for v in values], ['control_start', 'combined', 'control_end'])
        self.assertEqual(sum(len(v['modes']) * 3 * 3 for v in values), 81)
        for v in (values[0], values[2]):
            self.assertEqual((v['batch'], v['early'], v['tokens'], v['wait_ms']), (0, 0, 12, 0))
        self.assertEqual(tuple(values[1][key] for key in ('batch','early','tokens','wait_ms')), (4,1,4,0))
        with self.assertRaises(ValueError):
            experiment.arms('invalid')

    def test_missing_outputs_do_not_claim_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = report.build_report(root / 'baseline', root / 'screen')
            self.assertFalse(value['complete'])
            self.assertEqual(value['baseline']['status'], 'pending')
            self.assertIn('尚未完成', report.render_markdown(value))


class ReportEvidenceTests(unittest.TestCase):
    def event(self, name, **fields):
        return {'response_id': 'a', 'clock_domain': 'process:1', 'monotonic_ns': 0,
                'event': name, **fields}

    def test_missing_token_events_are_missing_not_success(self):
        value = report.trace_checks([self.event('audio_frame')], [{'response_id': 'a', 'mode': 'sparse'}])
        row = value['responses']['a']
        self.assertFalse(row['token_observation_complete'])
        self.assertIsNone(row['token_order_equal'])
        self.assertIsNone(row['new_graphs'])

    def test_token_loss_and_new_graph_are_reported(self):
        events = [self.event('text.tokens', token_ids=[1, 2, 3], monotonic_ns=100000000),
                  self.event('text.consumed', token_ids=[1, 2]),
                  self.event('text.remaining', count=1),
                  self.event('model.prefill.start', monotonic_ns=300000000),
                  self.event('compile.state', phase='prefill.before', unique_graphs=3),
                  self.event('model.frame_summary', frame=1, unique_graphs=4, wall_seconds=.15, eager=0, compiled=1)]
        row = report.trace_checks(events, [{'response_id': 'a', 'mode': 'sparse'}])['responses']['a']
        self.assertFalse(row['token_order_equal'])
        self.assertEqual(row['remaining_tokens'], 1)
        self.assertEqual(row['new_graphs'], 1)
        self.assertAlmostEqual(row['worker_text_to_prefill_seconds'], .2)

    def test_pairs_match_identity_and_keep_pcm_equality(self):
        base = {'id': 'one', 'mode': 'whole', 'repeat': 0, 'error': None,
                'first_pcm_seconds': 1., 'audible_estimate_seconds': 2., 'audio_sha256': 'same'}
        candidate = {**base, 'first_pcm_seconds': .7, 'audible_estimate_seconds': 1.8}
        value = report.compare_runs({'rows': [base]}, {'rows': [candidate,
            {**candidate, 'id': 'other'}, {**candidate, 'repeat': 1}]}, require_pcm=True)['whole']
        self.assertEqual(value['matched_attempts'], 1)
        self.assertEqual(value['pcm_equal'], 1)
        self.assertAlmostEqual(value['first_pcm_saved_seconds']['mean'], .3)


if __name__ == '__main__':
    unittest.main()
