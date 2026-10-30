"""Check uncertainty, causal evidence and planned denominators in trace scoring."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/training'))
import score_textturn_trace as scoring


class TextTurnTraceScoringTests(unittest.TestCase):
    def case(self, category='backchannel'):
        return {'case_id': 'case', 'source_id': 'source', 'category': category,
                'reference_text': 'I see.' if category == 'backchannel' else 'A complete statement.'}

    def context(self, text, at=1.):
        return {'kind': 'context_publish', 'event_seq': 2, 'version': 1, 'asr_prefix_version': 1,
                'text': text, 'published_at': at}

    def control(self, text, action='keep', state='Speak', at=1.2):
        return {'kind': 'control_result', 'action': action, 'started_at': at,
                'returned_at': at + .05, 'control_ms': 50,
                'visible': {'state': state, 'user_text': text, 'observation': '<|no-voice|>'},
                'window': {'last_step_seq': 3, 'text': text, 'asr_prefix_version': 1}}

    def test_unrecognized_backchannel_is_unknown_not_error_or_success(self):
        rows, _ = scoring.score_trace(self.case(), [self.context('I'), self.control('I')])
        result = scoring.outcome_metric(rows, negative=True)
        self.assertEqual((result['planned'], result['unknown'], result['actual_errors']), (1, 1, 0))
        self.assertIsNone(result['rate'])
        self.assertEqual(result['planned_error_bounds'], [0., 1.])

    def test_false_stop_survives_later_keep_and_reference_mismatch(self):
        case = self.case()
        case['reference_text'] = 'Hmm.'
        rows, _ = scoring.score_trace(case, [self.context('I see.'), self.control('I see.', 'stop'),
                                             self.control('I see.', 'keep', 'Listen', 1.5)])
        self.assertFalse(rows[0]['reference_matched'])
        self.assertEqual(rows[0]['outcome'], 'fail')
        self.assertTrue(rows[0]['actual_error'])

    def test_missing_pause_control_is_unknown(self):
        rows, _ = scoring.score_trace(self.case('smooth_question_pause'), [])
        pause = next(r for r in rows if r['metric'] == 'pause_false_start')
        self.assertEqual(pause['outcome'], 'unknown')
        self.assertFalse(pause['actual_error'])

    def test_whole_reference_or_future_sentence_does_not_label_early_start(self):
        case = self.case('smooth_declarative')
        events = [self.context('A complete statement.'), self.control('A complete statement.', 'start', 'Listen')]
        row = scoring.score_trace(case, events)[0][0]
        self.assertEqual(row['outcome'], 'unknown')
        case['reference_text'] += ' A future sentence.'
        new = scoring.score_trace(case, events)[0][0]
        self.assertEqual((row['outcome'], row['actual_error']), (new['outcome'], new['actual_error']))

    def test_reviewed_anchor_includes_transport_and_rejects_stale_input(self):
        context = self.context('A complete statement.')
        control = self.control('A complete statement.', 'start', 'Listen', 1.951)
        review = {'reviewer': 'contract_fixture', 'reason': 'Current complete content with yield observation.',
                  'anchor': {'context_event_seq': 2, 'text_sha256': scoring.canonical_hash(context['text'])},
                  'decisions': [{'last_step_seq': 3, 'visible_sha256': scoring.canonical_hash(control['visible']), 'target': 'start'}]}
        row = scoring.score_trace(self.case('smooth_declarative'), [context, control], review)[0][0]
        self.assertEqual(row['outcome'], 'fail')
        control['returned_at'] = 2.
        self.assertEqual(scoring.score_trace(self.case('smooth_declarative'), [context, control], review)[0][0]['outcome'], 'pass')
        control['window']['asr_prefix_version'] = 0
        self.assertEqual(scoring.score_trace(self.case('smooth_declarative'), [context, control], review)[0][0]['outcome'], 'unknown')
        control['visible']['user_text'] = 'changed'
        with self.assertRaises(ValueError):
            scoring.score_trace(self.case('smooth_declarative'), [context, control], review)

    def test_literal_stop_word_without_command_is_not_interruption(self):
        for text in ["Don't stop", 'The stop sign', 'stopwatch', 'Please']:
            self.assertFalse(scoring.is_interruption(text))
        self.assertTrue(scoring.is_interruption('Wait,'))

    def test_unknown_can_never_disappear_from_verdict(self):
        rows = [{'outcome': 'pass', 'actual_error': False}] * 173 + [{'outcome': 'unknown', 'actual_error': False}] * 127
        value = scoring.outcome_metric(rows, negative=True)
        self.assertEqual(value['rate'], 0.)
        self.assertEqual(value['planned'], 300)
        self.assertEqual(scoring.threshold_verdict(value, negative=True), 'insufficient_evidence')
