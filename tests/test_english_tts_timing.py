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


class SpokenTimeTests(unittest.TestCase):
    """Keep clock normalization restricted to the spoken copy."""

    def test_explicit_clock_times_and_unrelated_numbers(self):
        spec = importlib.util.spec_from_file_location('kokoro_service',
            Path(__file__).parents[1] / 'scripts/remote/kokoro_tts_service.py')
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)
        self.assertEqual(service.spoken_time_text('Tuesday at 9:30, or Thursday at 3:15?'),
                         'Tuesday at nine thirty, or Thursday at three fifteen?')
        self.assertEqual(service.spoken_time_text('At 09:05 and before 00:00.'),
                         "At nine oh five and before zero o'clock.")
        for text in ['ratio 3:15', 'at 9:75', 'at 24:30', 'value 3.14', 'at 9:30:15']:
            self.assertEqual(service.spoken_time_text(text), text)


if __name__ == '__main__':
    unittest.main()
