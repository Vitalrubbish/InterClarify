"""Verify causal punctuation visibility without altering supervision schedules."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/training'))
from asr_surface import apply_asr_surface, audit_asr_surface
from layer1_data import MicroTurnPlanner, SequenceEncoder
from train_layer1 import validate_sequence
import test_layer1_data_pipeline as fixtures


def event(number, text='', turn=0):
    return {'event_id': number, 'user_text': text, 'user_origin': {'turn': turn} if text else None}


class AsrSurfaceTests(unittest.TestCase):
    def test_pause_does_not_release_punctuation_and_continuation_does(self):
        plan = {'events': [event(0, 'Ready?'), event(1), event(2), event(3, ' I can continue.') ]}
        apply_asr_surface(plan)
        self.assertEqual([e['user_asr'] for e in plan['events']], ['Ready', '', '', '? I can continue'])
        self.assertEqual(plan['asr_pending']['text'], '.')
        self.assertEqual(audit_asr_surface(plan)['punctuation_delayed_across_events'], 1)

    def test_shared_prefix_is_independent_of_future_continuation(self):
        prefix = [event(0, 'Ready?'), event(1)]
        short = apply_asr_surface({'events': copy.deepcopy(prefix)})
        long = apply_asr_surface({'events': copy.deepcopy(prefix) + [event(2, ' Yes.')]})
        self.assertEqual(short['events'], long['events'][:2])
        self.assertEqual(short['asr_pending']['text'], '?')

    def test_interruption_and_backchannel_release_previous_turn_punctuation(self):
        for origin in ({'turn': 2}, None):
            new = event(2, 'Actually, wait!', 2)
            new['user_origin'] = origin
            plan = apply_asr_surface({'events': [event(0, 'Ready?'), event(1), new]})
            self.assertEqual(new['user_asr'], '? Actually, wait')
            self.assertEqual(plan['asr_pending']['text'], '!')
            audit_asr_surface(plan)

    def test_same_window_continuation_preserves_internal_marks_and_contractions(self):
        plan = apply_asr_surface({'events': [event(0, "Don't stop. I'll help, now.")]})
        self.assertEqual(plan['events'][0]['user_asr'], "Don't stop. I'll help, now")
        audit_asr_surface(plan)

    def test_auditor_rejects_early_punctuation_and_repeated_sources(self):
        plan = apply_asr_surface({'events': [event(0, 'Ready?'), event(1), event(2, ' Yes.')]})
        early = copy.deepcopy(plan)
        early['events'][0]['user_asr'] = 'Ready?'
        early['events'][0]['asr_spans'][0]['end'] += 1
        with self.assertRaises(AssertionError):
            audit_asr_surface(early)
        duplicated = copy.deepcopy(plan)
        duplicated['events'][2]['asr_spans'].append({'source_event_id': 0, 'start': 0, 'end': 1})
        duplicated['events'][2]['user_asr'] += 'R'
        with self.assertRaises(AssertionError):
            audit_asr_surface(duplicated)

    def test_new_dialogue_resets_pending_and_retains_eof_residue(self):
        first = apply_asr_surface({'events': [event(0, 'Ready?!')]})
        second = apply_asr_surface({'events': [event(0, 'New request.')]})
        self.assertEqual(first['asr_pending']['text'], '?!')
        self.assertEqual(second['events'][0]['user_asr'], 'New request')
        audit_asr_surface(first)
        audit_asr_surface(second)

    def test_planner_changes_only_view_and_encoder_masks_user_text(self):
        config = copy.deepcopy(fixtures.CONFIG)
        tokenizer = fixtures.CharacterTokenizer()
        dialogue = {'dialogue_id': 'causal', 'split': 'train', 'texts': [
            'Are you ready? I have another question.', 'Certainly, go ahead.',
            'Actually explain this one!', 'Here is the answer.']}
        baseline = MicroTurnPlanner(tokenizer, config).plan(dialogue, 0)
        config['generation']['asr_surface'] = 'delayed_punctuation_v1'
        plan = MicroTurnPlanner(tokenizer, config).plan(dialogue, 0)
        self.assertEqual([{k: v for k, v in e.items() if k not in ('user_asr', 'asr_spans')}
                          for e in plan['events']], baseline['events'])
        audit_asr_surface(plan)
        sequences = list(SequenceEncoder(tokenizer, config, 256).encode(plan, 'train', 'ASR', 'asr_delayed'))
        for row in sequences:
            validate_sequence(row)
        covered = [s['event_id'] for row in sequences for s in row['spans'] if s['supervised']]
        self.assertEqual(covered, list(range(len(plan['events']))))


if __name__ == '__main__':
    unittest.main()
