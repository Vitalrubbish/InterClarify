"""Check reproducible human-review sampling without manufacturing approvals."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))
from layer1_data import digest, file_digest, write_json
import prepare_layer1_review as review


class ReviewTests(unittest.TestCase):
    def test_stratified_sampling_distinct_dialogues_balanced_splits_and_pending_labels(self):
        candidates = []
        for behavior in review.BEHAVIORS:
            for split in ('train', 'dev', 'test'):
                for identity in range(30):
                    for event_id in (0, 1):
                        candidates.append({'behavior': behavior, 'split': split,
                                           'dialogue_id': f'{split}-{identity}', 'event_id': event_id})
        selected, coverage = review.choose_events(candidates, 123, 20, 4)
        self.assertEqual((selected, coverage), review.choose_events(list(reversed(candidates)), 123, 20, 4))
        self.assertEqual(len(selected), 120)
        self.assertEqual(sum(r['required_reviewers'] == 2 for r in selected), 24)
        self.assertTrue(all(r['selected'] == r['requested'] for r in coverage))
        for behavior in review.BEHAVIORS:
            group = [r for r in selected if r['behavior'] == behavior]
            self.assertEqual(len({r['dialogue_id'] for r in group}), 20)
            self.assertEqual(sum(r['split'] == 'train' for r in group), 12)
        self.assertTrue(all(r['accepted'] is None and r['reviewer'] is None
                            for event in selected for r in event['reviews']))

    def test_missing_behavior_coverage_is_reported_without_duplicate_fill(self):
        rows = [{'behavior': 'natural_pause', 'split': 'train', 'dialogue_id': 'one', 'event_id': 0}]
        selected, coverage = review.choose_events(rows, 123, 20, 4)
        self.assertEqual(len(selected), 1)
        self.assertTrue(any(r['selected'] < r['requested'] for r in coverage))
        with self.assertRaises(ValueError):
            review.choose_events(rows, 123, 3, 4)

    def test_review_export_binds_artifacts_and_keeps_human_review_pending(self):
        class Tokenizer:
            fingerprint = {'fixture': 'tokenizer'}

            def __init__(self, *args):
                pass

            def decode(self, ids):
                return 'Answer.' if ids else ''

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dialogues').mkdir()
            dialogue = {'dialogue_id': 'one', 'split': 'train', 'texts': ['Question?', 'Answer.']}
            source = root / 'dialogues.json'
            write_json(source, [dialogue])
            relative = 'dialogues/' + digest('one') + '.json'
            event = {'event_id': 0, 'kind': 'response_start', 'user_text': 'Question?',
                     'user_unpunctuated': 'Question', 'control': 'finish', 'assistant_ids': [1]}
            write_json(root / relative, {'plan': {'events': [event]}})
            write_json(root / 'manifest.json', {'complete': True, 'selected_sha256': file_digest(source),
                'identity': {'config': {'token_ids': {}}, 'tokenizer': Tokenizer.fingerprint},
                'artifacts': {relative: file_digest(root / relative)}})
            audit_path = root / 'audit.json'
            write_json(audit_path, {'machine_passed': True, 'manifest_sha256': file_digest(root / 'manifest.json')})
            args = argparse.Namespace(dataset=root, audit=audit_path, tokenizer=root, output=root / 'review',
                                      seed=123, per_behavior=5, double_per_behavior=1)
            with patch.object(review, 'ReleasedTokenizer', Tokenizer):
                summary = review.prepare(args)
            self.assertFalse(summary['human_review_complete'])
            self.assertFalse(summary['training_allowed'])
            template = json.loads((args.output / 'human_review_template.json').read_text())
            self.assertIsNone(template['minimum_set'][0]['accepted'])
            self.assertEqual(template['minimum_set'][0]['sha256'], file_digest(root / relative))
            self.assertIn('Question?', (args.output / 'minimum_32.md').read_text())
            self.assertFalse((root / 'human_review.json').exists())
            write_json(root / relative, {'corrupted': True})
            args.output = root / 'other-review'
            with patch.object(review, 'ReleasedTokenizer', Tokenizer), self.assertRaisesRegex(ValueError, 'checksum'):
                review.prepare(args)


if __name__ == '__main__':
    unittest.main()
