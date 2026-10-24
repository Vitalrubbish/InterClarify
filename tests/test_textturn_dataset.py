"""Small contract checks for TextTurn data compilation, without model weights."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    'textturn_dataset', Path(__file__).parents[1] / 'scripts/training/build_textturn_dataset.py')
dataset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dataset)


class TextTurnDatasetTests(unittest.TestCase):
    def setUp(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
        backend = Tokenizer(models.BPE(vocab={c: i for i, c in enumerate(alphabet)}, merges=[]))
        backend.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        backend.save(str(Path(self.directory.name) / 'tokenizer.json'))
        self.tokenizer = dataset.ControlTokenizer(self.directory.name)
        self.source = {'texts': ['How can I', 'Here is an explanation.', 'UNSEEN FUTURE'],
                       'source_revision': dataset.SOURCE_REVISION}

    def plan(self, phases, state='Listen'):
        plan = {'scenario_id': 'contract', 'source_id': 'source', 'category': 'pause',
                'state': state, 'history_before_turn': 0, 'phases': phases}
        if state == 'Speak':
            plan['assistant_visible'] = {'source_turn': 1}
        return plan

    def test_chunks_preserve_unicode_and_punctuation(self):
        for text in [' café 中文🙂!', '3.14 is a number.', 'U.S.', 'end?']:
            chunks = list(self.tokenizer.chunks(text))
            self.assertEqual(''.join(chunks), text)
            self.assertTrue(all(dataset.strip_terminal(piece).strip() for piece in chunks))
        self.assertEqual(dataset.strip_terminal('Use 3.14?'), 'Use 3.14')
        self.assertEqual(dataset.strip_terminal('in the U.S.'), 'in the U.S.')

    def test_silence_rounds_duration_and_masks_only_action(self):
        plan = self.plan([{'channel': 'user', 'source_turn': 0},
                          {'channel': 'silence', 'duration_ms': 600,
                           'action': 'keep', 'reason_zh': '宾语未完成。'}])
        events, rows = dataset.compile_scenario(plan, self.source, self.tokenizer, 20000)
        self.assertEqual(sum(e['kind'] == 'silence' for e in events), 4)
        row = rows[-1]
        self.assertEqual(row['visible']['observation'], dataset.SILENCE)
        self.assertEqual([x for x in row['labels'] if x != -100],
                         [self.tokenizer.special[dataset.ACTIONS['keep']]])
        self.assertNotIn('UNSEEN FUTURE', row['prompt'])
        self.assertNotIn('reason_zh', row['prompt'])
        self.assertTrue(all(x == -100 for x in rows[0]['labels']))

    def test_visible_prefix_does_not_depend_on_future(self):
        phases = [{'channel': 'user', 'source_turn': 0},
                  {'channel': 'user', 'text': 'UNSEEN FUTURE', 'origin': 'synthetic_annotation'}]
        _, rows = dataset.compile_scenario(self.plan(phases), self.source, self.tokenizer, 20000)
        self.assertNotIn('UNSEEN FUTURE', rows[0]['prompt'])
        self.assertIn('UNSEEN FUTURE', rows[1]['prompt'])

    def test_natural_completion_has_no_stop_target(self):
        phases = [{'channel': 'silence', 'duration_ms': 160, 'action': 'keep', 'reason_zh': '继续播放。'},
                  {'channel': 'playback_complete'}]
        events, rows = dataset.compile_scenario(self.plan(phases, 'Speak'), self.source, self.tokenizer, 20000)
        self.assertEqual(events[-1]['state_after'], 'Listen')
        self.assertEqual([r['target_action'] for r in rows], ['keep'])

    def test_illegal_labels_and_unmarked_insertions_are_rejected(self):
        for state, action in [('Listen', 'stop'), ('Speak', 'start')]:
            with self.assertRaises(ValueError):
                dataset.compile_scenario(self.plan([
                    {'channel': 'silence', 'duration_ms': 160, 'action': action, 'reason_zh': '非法动作。'}
                ], state), self.source, self.tokenizer, 20000)
        with self.assertRaises(ValueError):
            dataset.source_text({'text': 'unmarked'}, self.source['texts'])


if __name__ == '__main__':
    unittest.main()
