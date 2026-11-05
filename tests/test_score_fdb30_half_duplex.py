"""Preserve current FDB turn thresholds when retiring the old replay stack."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/remote'))
from score_fdb30_half_duplex import behavior


class TimingRuleTests(unittest.TestCase):
    def test_turn_thresholds_and_negative_latency(self):
        cases = [
            ([(1.1, 1.3), (1.4, 1.6), (1.7, 1.9)], 0, None),
            ([(1.1, 1.2)] * 4, 1, .1),
            ([(.2, .5), (.6, 1.2)], 1, 0),
        ]
        for timestamps, tor, latency in cases:
            with self.subTest(timestamps=timestamps):
                result = behavior([{'timestamp': list(pair)} for pair in timestamps], 1)
                self.assertEqual(result['tor'], tor)
                if latency is None:
                    self.assertIsNone(result['latency'])
                else:
                    self.assertAlmostEqual(result['latency'], latency)

    def test_missing_response_has_no_latency(self):
        self.assertEqual(behavior([], 1), {'tor': 0, 'latency': None})


if __name__ == '__main__':
    unittest.main()
