"""Distinguish embedded silence from actual PCM supply starvation."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location('component_verification',
    Path(__file__).parents[1] / 'scripts/remote/verify_english_components.py')
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class TTSTimingTests(unittest.TestCase):
    """Make an on-time silent boundary visible without inventing underflow."""

    def test_embedded_silence_is_separate_from_supply_gaps(self):
        audio = np.concatenate([np.zeros(14400), np.full(9600, 3000), np.zeros(19200)])
        pcm = audio.astype('<i2').tobytes()
        packets = [{'arrival_seconds': .1}, {'arrival_seconds': .2}]
        timeline = [{'kind': 'pcm', 'bytes': len(pcm), 'compute_seconds': .1}] * 2
        metrics, played = verification.tts_timing_metrics([pcm, pcm], packets, timeline)
        self.assertAlmostEqual(metrics['simulated_underflow_seconds'], 0)
        self.assertAlmostEqual(metrics['max_boundary_silence_seconds'], .7)
        self.assertAlmostEqual(metrics['segment_timing'][0]['compute_realtime_factor'], .1 / .9)
        self.assertEqual(played, pcm + pcm)

    def test_supply_gap_is_included_in_listening_audio(self):
        pcm = np.full(9600, 3000, dtype='<i2').tobytes()
        packets = [{'arrival_seconds': .1}, {'arrival_seconds': .6}]
        timeline = [{'kind': 'pcm', 'bytes': len(pcm)}] * 2
        metrics, played = verification.tts_timing_metrics([pcm, pcm], packets, timeline)
        self.assertAlmostEqual(metrics['simulated_underflow_seconds'], .3)
        self.assertEqual(metrics['segments_shorter_than_600ms'], 2)
        self.assertEqual(metrics['max_boundary_silence_seconds'], 0)
        self.assertEqual(len(played), len(pcm) * 2 + round(.3 * 96000))


if __name__ == '__main__':
    unittest.main()
