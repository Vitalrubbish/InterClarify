"""Verify the ASR contract summarizer on synthetic event streams.

The comparison decides a runtime contract, so the accounting has to be exact:
raw rewrites and visible (committed-prefix) rewrites are counted separately, the
commit lag is measured from the end of the user's audio, and the per-arm final
transcripts are compared with a word-level distance.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'summarize_asr_contract',
    Path(__file__).resolve().parents[1] / 'scripts/remote/summarize_asr_contract.py')
summarize = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = summarize
SPEC.loader.exec_module(summarize)


def write_sample(root: Path, arm: str, subset: str, sample: str, events: list[dict]) -> None:
    """Write one sample's events below ``<run>/<arm>/<subset>__<sample>``.

    ``asr-smoke --audio-dir`` names its output directory after the basename of the
    input directory, so the node job stages ``<subset>__<sample>`` labels to keep
    the subsets apart.
    """
    directory = root / arm / f'{subset}__{sample}'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'asr_events.jsonl').open('w', encoding='utf-8') as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + '\n')


def partial(audio_seconds: float, arrival: float, text: str, visible: str,
            rewritten: bool = False, visible_rewritten: bool = False,
            **extra) -> dict:
    """Build one partial event, with optional extra fields."""
    event = {'audio_seconds': audio_seconds, 'arrival_seconds': arrival, 'text': text,
             'rewritten': rewritten, 'visible_text': visible,
             'visible_rewritten': visible_rewritten}
    event.update(extra)
    return event


class WordDistanceTests(unittest.TestCase):
    """The word-level distance is the decision metric between arms."""

    def test_identical_transcripts_are_zero(self) -> None:
        """Same words in the same order are distance 0."""
        self.assertEqual(summarize.word_distance('a b c', 'a b c'), 0)

    def test_counts_insertions_and_substitutions(self) -> None:
        """Distance counts changed words, not characters."""
        self.assertEqual(summarize.word_distance('a b c', 'a x c'), 1)
        self.assertEqual(summarize.word_distance('a b', 'a b c'), 1)
        self.assertEqual(summarize.word_distance('', 'a b'), 2)


class SampleStreamTests(unittest.TestCase):
    """One sample's contract is read from its own event stream."""

    def test_counts_rewrites_and_commit_lag(self) -> None:
        """Raw and visible rewrites are counted separately; lag starts at audio end."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_sample(root, 'window-0', 'subset', '1', [
                partial(1.0, 1.0, 'hello', 'hello'),
                partial(2.0, 2.1, 'hello world', 'hello'),
                partial(3.0, 3.2, 'hello web world', 'hello world', rewritten=True),
                {'final': True, 'arrival_seconds': 3.4, 'text': 'hello world',
                 'visible_text': 'hello world'},
            ])
            row = summarize.sample_stream(root / 'window-0' / 'subset__1')
        self.assertIsNotNone(row)
        self.assertEqual(row['partials'], 3)
        self.assertEqual(row['raw_rewrites'], 1)
        self.assertEqual(row['visible_rewrites'], 0)
        self.assertAlmostEqual(row['audio_seconds'], 3.0, places=6)
        # 'world' enters the raw transcript at 2.1s and the committed one at 3.2s
        self.assertAlmostEqual(row['commit_lag_seconds'], 1.1, places=6)
        # per-tick lag of the committed prefix behind the raw decode is 0,1,1
        self.assertEqual(row['held_back_words'], 1)
        self.assertEqual(row['visible_final_text'], 'hello world')
        self.assertEqual(row['visible_partial_text'], 'hello world')

    def test_visible_rewrite_is_reported(self) -> None:
        """A replaced visible transcript must be visible in the summary."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_sample(root, 'window-2', 'subset', '1', [
                partial(1.0, 1.0, 'hello', 'hello'),
                partial(2.0, 2.0, 'hello world', 'other text',
                        visible_rewritten=True),
            ])
            row = summarize.sample_stream(root / 'window-2' / 'subset__1')
        self.assertEqual(row['visible_rewrites'], 1)

    def test_healthy_commit_reports_no_freeze(self) -> None:
        """A prefix that stays within a few words is not the failure mode."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_sample(root, 'window-0', 'subset', '1', [
                partial(1.0, 1.0, 'w1 w2 w3 w4 w5 w6', 'w1 w2 w3 w4 w5'),
                partial(2.0, 2.0, 'w1 w2 w3 w4 w5 w6 w7', 'w1 w2 w3 w4 w5 w6'),
            ])
            row = summarize.sample_stream(root / 'window-0' / 'subset__1')
        self.assertEqual(row['commit_stalls'], 0)
        self.assertEqual(row['freeze_seconds'], 0.0)

    def test_frozen_commit_is_reported(self) -> None:
        """A stalled commit shows up as freeze seconds and a stall count."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = 'w1 w2'
            growing = ' '.join(f'w{i}' for i in range(1, 13))
            write_sample(root, 'window-0', 'subset', '1', [
                partial(1.0, 1.0, growing, frozen),
                partial(1.5, 1.5, growing, frozen, commit_stalls=3),
                partial(2.0, 2.0, growing, frozen, commit_stalls=3),
            ])
            row = summarize.sample_stream(root / 'window-0' / 'subset__1')
        self.assertEqual(row['commit_stalls'], 3)
        self.assertGreaterEqual(row['freeze_seconds'], 1.0)

    def test_missing_stream_yields_nothing(self) -> None:
        """An arm without events contributes no row instead of a fake one."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(summarize.sample_stream(Path(tmp) / 'nope'))


class ReportTests(unittest.TestCase):
    """The report compares every arm against the configured baseline."""

    def test_report_counts_arms_and_distances(self) -> None:
        """The wider window changes the text; the baseline distance stays 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            report = Path(tmp) / 'report'
            for sample in ('1', '2'):
                write_sample(root, 'window-0', 'subset', sample, [
                    partial(2.0, 2.0, 'hello world', 'hello world'),
                    {'final': True, 'arrival_seconds': 2.1, 'text': 'hello world',
                     'visible_text': 'hello world'},
                ])
                write_sample(root, 'window-2', 'subset', sample, [
                    partial(1.0, 1.0, 'hello', 'hello'),
                    partial(2.0, 2.1, 'hello world now', 'hello world'),
                    {'final': True, 'arrival_seconds': 2.2, 'text': 'hello world now',
                     'visible_text': 'hello world now'},
                ])
            with patch.object(sys, 'argv', [
                    'summarize', '--run-dir', str(root), '--report-dir', str(report),
                    '--tag', 'test']):
                self.assertEqual(summarize.main(), 0)
            markdown = (report / 'asr_contract.md').read_text(encoding='utf-8')
            payload = json.loads((report / 'asr_contract.json').read_text(encoding='utf-8'))
        self.assertIn('window-0', markdown)
        self.assertIn('window-2', markdown)
        self.assertIn('提交延迟', markdown)
        self.assertEqual(payload['arms']['window-0']['summary']['samples'], 2)
        self.assertEqual(payload['arms']['window-0']['summary']['raw_rewrites'], 0)
        self.assertEqual(
            payload['arms']['window-2']['summary']['visible_final_distance_median'], 1.0)
        self.assertEqual(
            payload['arms']['window-0']['summary']['visible_final_distance_median'], 0.0)
        self.assertAlmostEqual(
            payload['arms']['window-2']['summary']['commit_lag_median_seconds'], 0.1,
            places=6)
        self.assertEqual(
            payload['arms']['window-2']['summary']['held_back_words_median'], 0.5)
        self.assertEqual(
            payload['arms']['window-0']['summary']['held_back_words_median'], 0)
        self.assertAlmostEqual(
            payload['arms']['window-0']['summary']['commit_lag_median_seconds'], 0.0,
            places=6)


if __name__ == '__main__':
    unittest.main()
