"""Prove exclusion coverage gaps stay visible and external text blocks source turns."""

import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))
import build_layer1_exclusions as exclusions
import layer1_data as data


class ExclusionTests(unittest.TestCase):
    def setup_sources(self, root):
        config = {'schema_version': 1, 'fdb_counts': {'subset': 1}, 'fleurs_count': 1,
                  'historical_count': 1, 'text_keys': ['text', 'reference', 'context', 'interrupt'],
                  'ignored_markers': ['[TURN-TAKING]']}
        path = root / 'config.yaml'
        path.write_text(yaml.safe_dump(config))
        fleurs = root / 'fleurs.json'
        data.write_json(fleurs, {'repo': 'google/fleurs', 'revision': 'frozen',
                                'samples': [{'sample_id': 'test/one', 'reference': 'Protect this evaluation utterance.'}]})
        history = root / 'history.json'
        data.write_json(history, {'samples': [{'id': 'historical-1', 'word_events': [
            {'text': 'Hello'}, {'text': 'there.'}]}]})
        sample = root / 'fdb/subset/1'
        sample.mkdir(parents=True)
        data.write_json(sample / 'annotation.json', [{'text': '[TURN-TAKING]', 'timestamp': [1, 2]}])
        return argparse.Namespace(config=path, fleurs_manifest=fleurs, historical_manifest=history,
                                  fdb_root=root / 'fdb', output=root / 'excluded.json')

    def test_missing_fdb_text_is_not_reviewed_even_with_exact_sample_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_sources(Path(tmp))
            result = exclusions.build(args)
            self.assertFalse(result['reviewed'])
            self.assertEqual(result['missing'], [{'scope': 'fdb/subset', 'sample_id': '1', 'reason': 'no_text'}])
            self.assertEqual(result['ids'], [])
            self.assertIn(data.digest(data.normalized('Hello there.')), result['normalized_hashes'])
            self.assertNotIn(data.digest(data.normalized('[TURN-TAKING]')), result['normalized_hashes'])

    def test_complete_coverage_is_deterministic_and_includes_concatenated_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.setup_sources(Path(tmp))
            data.write_json(args.fdb_root / 'subset/1/transcription.json', [{'text': 'How are'}, {'text': 'you?'}])
            first = exclusions.build(args)
            self.assertTrue(first['reviewed'])
            self.assertIn(data.digest(data.normalized('How are you?')), first['normalized_hashes'])
            self.assertEqual(first, exclusions.build(args))

    def test_external_utterance_excludes_a_matching_turn_inside_longer_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.setup_sources(root)
            result = exclusions.build(args)
            config = yaml.safe_load((ROOT / 'configs/layer1_data.yaml').read_text())
            config['limits']['min_free_gib'] = 0
            source = root / 'source.jsonl'
            source.write_text(json.dumps({'id': 'ultrachat-99', 'data': [
                'Protect this evaluation utterance.', 'A completely different answer.']}) + '\n')
            index = data.DialogueIndex(root / 'index.sqlite3', config)
            try:
                index.ingest([source], result)
                self.assertEqual(index.db.execute('SELECT COUNT(*) FROM dialogues').fetchone()[0], 0)
                self.assertEqual(index.db.execute('SELECT reason FROM excluded').fetchone()[0], 'external_exclusion')
            finally:
                index.close()


if __name__ == '__main__':
    unittest.main()
