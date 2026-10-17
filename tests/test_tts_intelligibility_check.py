"""Check word-error accounting without loading an ASR model."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/remote'))
import tts_intelligibility_check as check


class WordErrorTests(unittest.TestCase):
    def test_normalization_and_edit_types(self):
        self.assertEqual(check.edit_counts('Yes, that works!', 'YES THAT WORKS')['errors'], 0)
        self.assertEqual(check.edit_counts('one two three', 'one three')['deletions'], 1)
        self.assertEqual(check.edit_counts('one two', 'one four')['substitutions'], 1)
        self.assertEqual(check.edit_counts('one two', 'one two three')['insertions'], 1)
        self.assertEqual(check.edit_counts('one two', '')['deletions'], 2)
        self.assertEqual(check.edit_counts('', 'one two')['insertions'], 2)

    def test_weighted_denominator_and_failure_separation(self):
        rows = [{'arm': 'a', 'error': None, 'edits': check.edit_counts('one', '')},
                {'arm': 'a', 'error': None, 'edits': check.edit_counts('one two three', 'one two three')},
                {'arm': 'a', 'error': 'fixture', 'edits': None}]
        value = check.summarize(rows)['a']
        self.assertEqual(value['failures'], 1)
        self.assertEqual(value['reference_words'], 4)
        self.assertEqual(value['wer'], .25)


if __name__ == '__main__':
    unittest.main()
