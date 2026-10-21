"""Protect subset score coverage and original-window versus tail diagnostics."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/remote'))
import fdb_subset_report as subset


class SubsetReportTests(unittest.TestCase):
    def test_scoring_uses_five_cases_and_restores_full_corpus_contract(self):
        original = dict(subset.full.AXES)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'score'
            def fake_score(args):
                self.assertTrue(all(row[1] == 5 for row in subset.full.AXES.values()))
                output.mkdir()
                (output / 'summary.json').write_text('{}')
                return 0
            with patch.object(subset.full, 'score', side_effect=fake_score):
                self.assertEqual(subset.score_subset(SimpleNamespace(output=output)), 0)
            self.assertEqual(subset.full.AXES, original)
            self.assertEqual(json.loads((output / 'summary.json').read_text())['expected_sessions'], 10)

    def fixture(self, root):
        for name in ('candor_pause_handling', 'synthetic_pause_handling', 'candor_turn_taking',
                     'synthetic_user_interruption', 'icc_backchannel'):
            for number in range(5):
                folder = root / 'fdb' / name / str(number)
                folder.mkdir(parents=True)
                for filename in ('input.wav', 'output.wav'):
                    with wave.open(str(folder / filename), 'wb') as audio:
                        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                        audio.writeframes(b'\x00\x00' * 16000)
                response = {'response_id': 'r', 'played_audio_bytes': 20,
                            'playback_started_seconds': .5 if number == 0 else 1.5,
                            'playback_started_in_tail': number != 0}
                report = {'input_audio_seconds': 1, 'transport_status': 'PASS',
                          'timeline': {'protocol_errors': []},
                          'client_measurements': {'responses': [response], 'latencies': {},
                                                  'anchors': {}, 'no_played_audio': False}}
                (folder / 'a4_report.json').write_text(json.dumps(report))

    def test_tail_only_playback_is_not_counted_in_original_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            report = subset.summarize(root, root / 'diagnostics.json')
            self.assertEqual(report['sessions'], 25)
            self.assertEqual(report['official_wav_durations_verified'], 25)
            for group in report['subsets']:
                self.assertEqual(group['played_in_original_window'], 1)
                self.assertEqual(group['played_only_in_tail'], 4)

    def test_missing_case_or_tail_in_official_wav_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            wav = root / 'fdb/candor_turn_taking/0/output.wav'
            with wave.open(str(wav), 'wb') as audio:
                audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\x00\x00' * 32000)
            with self.assertRaises(ValueError):
                subset.summarize(root, root / 'failed.json')
            (root / 'fdb/candor_pause_handling/0/a4_report.json').unlink()
            with self.assertRaises(ValueError):
                subset.summarize(root, root / 'missing.json')


if __name__ == '__main__':
    unittest.main()
