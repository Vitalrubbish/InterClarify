"""Check opportunity denominators, causal errors and observation-window timing."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    'score_textturn', Path(__file__).parents[1] / 'scripts/training/score_textturn.py')
scoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scoring)


class TextTurnScoringTests(unittest.TestCase):
    def row(self, identity, target, category='smooth', visible=960, allowed=480):
        return {'snapshot_id': identity, 'opportunity_id': 'one', 'category': category,
                'source_id': 'source', 'target_action': target, 'utterance_form': 'declarative',
                'visible_ms': visible, 'allowed_visible_ms': allowed}

    def test_earlier_false_start_cannot_be_repaired_by_correct_anchor(self):
        rows = [self.row('early', 'keep'), self.row('anchor', 'start')]
        predictions = [{'snapshot_id': key, 'action': 'start', 'control_ms': 10} for key in ('early', 'anchor')]
        result, _ = scoring.score_predictions(rows, predictions)
        self.assertEqual(result['smooth']['numerator'], 0)
        self.assertEqual(result['smooth']['denominator'], 1)

    def test_missing_wait_is_not_successful_pause(self):
        rows = [self.row('pause', 'keep', 'pause')]
        result, _ = scoring.score_predictions(rows, [])
        self.assertEqual(result['pause_false_start']['rate'], 1.)
        self.assertEqual(result['runtime']['denominator'], 1)

    def test_window_wait_is_included_in_timely_start(self):
        rows = [self.row('anchor', 'start')]
        prediction = {'snapshot_id': 'anchor', 'action': 'start', 'control_ms': 521}
        result, _ = scoring.score_predictions(rows, [prediction])
        self.assertEqual(result['smooth']['rate'], 0.)
        prediction['control_ms'] = 520
        result, _ = scoring.score_predictions(rows, [prediction])
        self.assertEqual(result['smooth']['rate'], 1.)


if __name__ == '__main__':
    unittest.main()
