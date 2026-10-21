"""Check surface classification and source-turn independence in audit samples."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/training'))
from audit_layer1_surface import boundary_kind, select_cards, strip_terminal, text_statistics, transcript_views


class SurfaceAuditTests(unittest.TestCase):
    def test_eof_only_text_is_counted_without_inventing_online_text(self):
        self.assertEqual(transcript_views([{'text': 'At last', 'eof': True}]), ('', 'At last'))
        self.assertEqual(transcript_views([{'text': 'Stop', 'eof': False}, {'text': 'Stop.', 'eof': True}]),
                         ('Stop', 'Stop.'))
        for broken in ([], [{'text': 'Invalid', 'eof': 'false'}]):
            with self.assertRaises(ValueError):
                transcript_views(broken)

    def test_internal_punctuation_survives_terminal_period_candidate(self):
        text = 'First, wait. Then ask "ready?".'
        self.assertEqual(strip_terminal(text), 'First, wait. Then ask "ready?"')
        self.assertEqual(text_statistics(text)['internal_chars_.'], 1)
        self.assertEqual(text_statistics(text)['internal_chars_,'], 1)
        self.assertEqual(text_statistics(text)['terminal_chars_.'], 1)
        self.assertEqual(strip_terminal('Is it ready?'), 'Is it ready?')
        self.assertEqual(strip_terminal('He said "ready."'), 'He said "ready"')

    def test_sentence_marks_and_numeric_or_incomplete_word_boundaries(self):
        self.assertEqual(boundary_kind('Stop. Then continue', 6), 'after_sentence_mark')
        self.assertEqual(boundary_kind('First, continue', 6), 'after_clause_mark')
        self.assertEqual(boundary_kind('Continue talking', 4), 'inside_word')
        self.assertEqual(boundary_kind('Continue talking', 9), 'other')
        self.assertEqual(strip_terminal('At 3.14'), 'At 3.14')
        self.assertEqual(text_statistics('At 3.14')['terminal_texts'], 0)

    def test_selection_is_stable_and_never_reuses_source_turn(self):
        shared = {'dialogue_id': 'shared', 'turn': 0, 'event_id': 1}
        candidates = {
            'sentence_mark_then_continues': [shared],
            'enumeration_or_repair_cue': [shared, {'dialogue_id': 'other', 'turn': 0, 'event_id': 3}],
            'inside_word': [{'dialogue_id': 'shared', 'turn': 2, 'event_id': 4}],
            'turn_end': [{'dialogue_id': 'final', 'turn': 0, 'event_id': 8}],
        }
        rows, coverage = select_cards(candidates, 17, 1)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({(r['dialogue_id'], r['turn']) for r in rows}), 4)
        self.assertEqual((rows, coverage), select_cards(candidates, 17, 1))
        self.assertTrue(all(r['semantic_review'] is None and r['human_review'] is None for r in rows))
        _, missing = select_cards({}, 17, 1)
        self.assertEqual(missing['inside_word']['selected'], 0)


if __name__ == '__main__':
    unittest.main()
