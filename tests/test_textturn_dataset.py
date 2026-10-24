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
            plan['assistant_stream'] = {'source_turn': 1}
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
        self.assertEqual(sum(e['kind'] == 'silence' for e in events), 2)
        self.assertEqual(events[-1]['rebuilt_duration_ms'], 960)
        self.assertEqual(len({r['visible']['consecutive_no_voice_windows'] for r in rows
                              if r['visible']['observation'] == dataset.SILENCE}), 2)
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
        self.assertIn('UNSEEN FUTURE', rows[-1]['prompt'])

    def test_natural_completion_has_no_stop_target(self):
        phases = [{'channel': 'generation', 'action': 'keep', 'reason_zh': '继续生成和播放。'},
                  {'channel': 'playback_tail', 'windows': [2, 2], 'action': 'keep', 'reason_zh': '仍有播放尾巴。'},
                  {'channel': 'playback_complete'},
                  {'channel': 'post_playback_wait', 'windows': [2, 2], 'action': 'keep', 'reason_zh': '等待用户下一轮开口。'}]
        plan = self.plan(phases, 'Speak')
        events, rows = dataset.compile_scenario(plan, self.source, self.tokenizer, 20000)
        self.assertEqual(next(e for e in events if e['kind'] == 'playback_complete')['state_after'], 'Listen')
        self.assertTrue(all(r['target_action'] == 'keep' for r in rows))
        tail = [e for e in events if e['kind'] == 'playback_tail']
        self.assertTrue(all(e['state'] == 'Speak' and e['assistant_generation_complete'] and not e['assistant_delta'] for e in tail))
        self.assertEqual(tail[0]['assistant_visible'], self.source['texts'][1])
        self.assertEqual(rows[-1]['visible']['state'], 'Listen')
        self.assertEqual(rows[-1]['visible']['history'][-1]['text'], self.source['texts'][1])
        with self.assertRaises(ValueError):
            dataset.compile_scenario(self.plan([{'channel': 'playback_complete'}], 'Speak'),
                                     self.source, self.tokenizer, 20000)

    def test_assistant_stream_is_incremental_and_step_size_is_effective(self):
        self.source['texts'][1] = 'ABCDEFGHIJKLMNO'
        phases = [{'channel': 'user', 'text': text, 'origin': 'synthetic_annotation',
                   'action': 'keep', 'reason_zh': '用户简短确认，当前继续表达。'}
                  for text in ['Hmm.', 'Yes']]
        plan = self.plan(phases, 'Speak')
        plan['assistant_lead_in_steps'] = 2
        events, rows = dataset.compile_scenario(plan, self.source, self.tokenizer, 20000,
                                               assistant_tokens_per_step=2, user_tokens_per_step=(2, 2))
        first = next(r for r in rows if r['visible']['user_text'] == 'Hmm')
        second = next(r for r in rows if r['visible']['user_text'] == 'Hmm.Yes')
        self.assertEqual(first['visible']['assistant_visible'], 'ABCDEFGH')
        self.assertEqual(second['visible']['assistant_visible'], 'ABCDEFGHIJKL')
        self.assertNotIn('IJKL', first['prompt'])
        self.assertNotIn('MNO', second['prompt'])
        self.assertTrue(all(e['assistant_delta_tokens'] == 2 for e in events))
        self.assertEqual(events[0]['observation'], dataset.SILENCE)
        _, slower = dataset.compile_scenario(plan, self.source, self.tokenizer, 20000,
                                              assistant_tokens_per_step=1, user_tokens_per_step=(2, 2))
        self.assertEqual(next(r for r in slower if r['visible']['user_text'] == 'Hmm')['visible']['assistant_visible'], 'ABCD')

    def test_random_user_widths_and_waits_are_reproducible(self):
        text = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        first = list(self.tokenizer.chunks(text, (1, 2), rng=dataset.seeded_rng(42, 'width')))
        second = list(self.tokenizer.chunks(text, (1, 2), rng=dataset.seeded_rng(42, 'width')))
        self.assertEqual(first, second)
        self.assertEqual(''.join(first), text)
        self.assertEqual({len(self.tokenizer.encode(piece)) for piece in first}, {1, 2})
        plan = self.plan([{'channel': 'silence', 'windows': [1, 3], 'action': 'keep', 'reason_zh': '用户表达未完成。'}])
        a = dataset.compile_scenario(plan, self.source, self.tokenizer, 20000)
        b = dataset.compile_scenario(plan, self.source, self.tokenizer, 20000)
        self.assertEqual(a, b)

    def test_illegal_labels_and_unmarked_insertions_are_rejected(self):
        for state, action in [('Listen', 'stop'), ('Speak', 'start')]:
            with self.assertRaises(ValueError):
                dataset.compile_scenario(self.plan([
                    {'channel': 'silence', 'duration_ms': 160, 'action': action, 'reason_zh': '非法动作。'}
                ], state), self.source, self.tokenizer, 20000)
        with self.assertRaises(ValueError):
            dataset.source_text({'text': 'unmarked'}, self.source['texts'])
        with self.assertRaises(ValueError):
            dataset.compile_scenario(self.plan([
                {'channel': 'user', 'text': 'Please', 'origin': 'synthetic_annotation',
                 'action': 'stop', 'trigger_text': 'stop', 'prefix_action': 'keep',
                 'prefix_reason_zh': '尚无停止依据。', 'reason_zh': '停止。'}
            ], 'Speak'), self.source, self.tokenizer, 20000)


if __name__ == '__main__':
    unittest.main()
