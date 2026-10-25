"""Exercise causal yield annotations and the single synthetic playback owner."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts' / 'training'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('yield_dataset', SCRIPTS / 'build_textturn_yield_dataset.py')
dataset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dataset)


class YieldDatasetTests(unittest.TestCase):
    def setUp(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
        backend = Tokenizer(models.BPE(vocab={c: i for i, c in enumerate(alphabet)}, merges=[]))
        backend.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        backend.save(str(Path(self.directory.name) / 'tokenizer.json'))
        self.tokenizer = dataset.ControlTokenizer(self.directory.name)
        self.source = dict(source_id='source', duplicate_group='group',
                           texts=['How can I learn?', 'A' * 120, 'I need examples.', 'B' * 40])

    def trace(self):
        trace = dataset.YieldTrace('test', self.tokenizer, self.source, 'train')
        trace.user = 'How can I learn?'
        trace.step('start', 'start', response=self.source['texts'][1])
        return trace

    def test_first_decidable_update_stops_without_stop_word(self):
        trace = self.trace()
        trace.user_segment('Add an example.', 'update', 3)
        stops = [r for r in trace.rows if r['target_action'] == 'stop']
        self.assertEqual(len(stops), 1)
        first = next(r for r in trace.rows if r['annotation']['judgment'] == 'non_backchannel')
        self.assertEqual(stops[0], first)
        self.assertNotIn('stop', first['visible']['user_text'].lower())
        self.assertEqual(first['stop_confirmed_ms'] - first['visible_ms'], 80)
        self.assertTrue(all(r['target_action'] != 'stop' for r in trace.rows if r['visible']['state'] == 'Listen'))
        stop_request = next(e for e in trace.events if e['kind'] == 'stop_requested')
        self.assertEqual(stop_request['state_after'], 'Speak')
        trace.validate()

    def test_backchannel_then_takeover_and_unknown_masks(self):
        trace = self.trace()
        trace.user_segment('Right', 'backchannel', backchannel=True)
        self.assertEqual(trace.state, 'Speak')
        self.assertEqual(trace.rows[-1]['target_action'], 'keep')
        trace.user_segment(', but add details.', 'change', 5)
        self.assertEqual(trace.state, 'Listen')
        unknown = [r for r in trace.rows if r['target_action'] is None]
        self.assertTrue(unknown)
        self.assertTrue(all(all(v == -100 for v in r['labels']) for r in unknown))
        self.assertNotIn('details', trace.rows[1]['prompt'])
        self.assertNotIn('judgment', trace.rows[-1]['prompt'])

    def test_duplicates_old_turns_and_revisions(self):
        trace = self.trace()
        self.assertEqual(trace.update('Right', 1, trace.turn), 'Right')
        for text, version, turn in [('Right', 2, trace.turn), ('Right', 1, trace.turn),
                                     ('old text', 9, trace.turn - 1)]:
            self.assertEqual(trace.update(text, version, turn), '')
        self.assertEqual(trace.user, 'Right')
        with self.assertRaises(ValueError):
            trace.update('Wrong revision', 3, trace.turn)

    def test_generation_end_tail_finish_and_persistent_terminal(self):
        trace = self.trace()
        output_id = trace.active['output_id']
        with self.assertRaises(ValueError):
            trace.callback(output_id)
        while not trace.active['generation_complete']:
            trace.step('no_update')
        self.assertEqual(trace.state, 'Speak')
        trace.user_segment('Add details.', 'tail_update', 3)
        trace.callback(output_id)
        self.assertEqual(trace.events[-1]['kind'], 'stale_callback')
        trace.validate()
        normal = self.trace()
        normal.drain()
        output_id = normal.outputs[0]['output_id']
        normal.step('consume')
        self.assertEqual(normal.rows[-1]['visible']['runtime_events'][0]['kind'], 'finish')
        normal.callback(output_id)
        normal.step('persist')
        self.assertEqual(normal.rows[-1]['visible']['runtime_events'], [])
        self.assertEqual(normal.rows[-1]['visible']['latest_terminal']['kind'], 'finish')
        self.assertEqual(sum(e['kind'] == 'finish' for e in normal.events), 1)
        normal.validate()

    def test_pretext_races_multiple_outputs_and_truncation(self):
        for variant, expected in [('pretext', 'stop'), ('finish_first', 'finish'),
                                  ('update_first', 'stop'), ('error', 'error'), ('truncated', 'truncated')]:
            timeline, rows = dataset.scenario(self.source, 'train', variant, self.tokenizer, 0)
            self.assertEqual(timeline['outputs'][0]['status'], expected)
            if variant == 'pretext':
                self.assertEqual(next(r for r in rows if r['target_action'] == 'stop')['visible']['assistant_visible'], '')
            if variant == 'finish_first':
                self.assertFalse(any(r['target_action'] == 'stop' for r in rows))
        timeline, rows = dataset.scenario(self.source, 'train', 'multiple', self.tokenizer, 0)
        self.assertEqual([o['status'] for o in timeline['outputs']], ['stop', 'stop'])
        self.assertEqual(len({o['output_id'] for o in timeline['outputs']}), 2)
        trace = self.trace()
        with self.assertRaises(ValueError):
            trace.validate()
        with self.assertRaises(ValueError):
            trace.accept_start('Rejected duplicate')


if __name__ == '__main__':
    unittest.main()
