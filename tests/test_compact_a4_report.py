"""Verify the A4 report compactor keeps verdicts and drops only raw streams."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'compact_a4_report', Path(__file__).parents[1] / 'scripts/remote/compact_a4_report.py')
compact_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compact_module
SPEC.loader.exec_module(compact_module)


class CompactTests(unittest.TestCase):
    """The compaction policy: counts instead of streams, truncation, no data loss."""

    def test_event_stream_becomes_histogram(self):
        """``events`` is replaced by a per-action count plus the tick span."""
        payload = {'events': [
            {'action': 'update_resp', 'seconds': 10.0, 'data': {'text': 'a'}},
            {'action': 'update_resp', 'seconds': 11.5, 'data': {'text': 'b'}},
            {'action': 'stop_tts', 'seconds': 12.0, 'data': {}},
        ]}
        result = compact_module.compact(payload)['events']
        self.assertEqual(result['ticks'], 3)
        self.assertEqual(result['by_event'], {'stop_tts': 1, 'update_resp': 2})
        self.assertAlmostEqual(result['span_seconds'], 2.0, places=3)

    def test_token_stream_becomes_histogram(self):
        """Marker streams are summarized by token, which is what the task order reads."""
        payload = {
            'timeline': {
                'raw_outputs': ['<|user is talking|>', '<|user is talking|>', '<|user interruption|>'],
                'protocol_tokens': ['<|no voice|>'],
            }
        }
        timeline = compact_module.compact(payload)['timeline']
        self.assertEqual(timeline['raw_outputs']['count'], 3)
        self.assertEqual(timeline['raw_outputs']['tokens']['<|user is talking|>'], 2)
        self.assertEqual(timeline['protocol_tokens']['tokens'], {'<|no voice|>': 1})

    def test_played_text_keeps_last_snapshot(self):
        """Played-text snapshots collapse to a count plus the final text (truncated)."""
        payload = {'timeline': {'played_text': {'resp-1': ['Hello', 'Hello world']}}}
        summary = compact_module.compact(payload)['timeline']['played_text']['resp-1']
        self.assertEqual(summary['snapshots'], 2)
        self.assertEqual(summary['last'], 'Hello world')

    def test_long_strings_are_truncated_with_a_marker(self):
        """Model replies keep a head plus an explicit dropped-length marker."""
        long_text = 'x' * (compact_module.MAX_STRING + 40)
        result = compact_module.compact({'response': long_text})['response']
        self.assertTrue(result.startswith('x' * compact_module.MAX_STRING))
        self.assertIn('truncated 40 chars', result)

    def test_scalars_and_ids_survive(self):
        """Verdict fields are untouched."""
        payload = {'status': 'PASS', 'errors': [], 'response_ids': ['r1'],
                   'first_audio_seconds': 1.25, 'tts_audio_bytes': 91}
        self.assertEqual(compact_module.compact(payload), payload)

    def test_csv_becomes_a_numeric_summary(self):
        """Sampler CSVs turn into row count plus per-column min/median/max."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'resource_samples.csv'
            path.write_text('proc,rss_mb,note\na,100,x\na,300,x\na,200,y\n', encoding='utf-8')
            summary = compact_module.summarize_csv(path)
            self.assertEqual(summary['rows'], 3)
            self.assertEqual(summary['columns']['rss_mb'],
                             {'min': 100.0, 'median': 200.0, 'max': 300.0})
            self.assertNotIn('note', summary['columns'])

    def test_main_rewrites_a_report_directory(self):
        """End to end: JSON compacted in place, CSV replaced by its summary."""
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)
            (report / 'replay').mkdir()
            (report / 'replay' / 'x_report.json').write_text(json.dumps({
                'status': 'PASS',
                'events': [{'action': 'start_tts', 'seconds': 1.0}],
            }), encoding='utf-8')
            (report / 'gpu_samples.csv').write_text('gpu,util\n0,10\n0,30\n', encoding='utf-8')

            argv = sys.argv
            sys.argv = ['compact_a4_report.py', '--report-dir', str(report)]
            try:
                self.assertEqual(compact_module.main(), 0)
            finally:
                sys.argv = argv

            compacted = json.loads((report / 'replay' / 'x_report.json').read_text())
            self.assertEqual(compacted['status'], 'PASS')
            self.assertEqual(compacted['events']['by_event'], {'start_tts': 1})
            self.assertFalse((report / 'gpu_samples.csv').exists())
            summary = json.loads((report / 'gpu_samples_summary.json').read_text())
            self.assertEqual(summary['columns']['util']['max'], 30.0)


if __name__ == '__main__':
    unittest.main()
