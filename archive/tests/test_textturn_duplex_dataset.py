"""Verify 160ms event sampling, causal labels and lifecycle ownership."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'training'))
SPEC = importlib.util.spec_from_file_location('duplex_dataset', ROOT / 'scripts/training/build_textturn_duplex_dataset.py')
dataset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dataset)


class DuplexDatasetTests(unittest.TestCase):
    def setUp(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
        backend = Tokenizer(models.BPE(vocab={c: i for i, c in enumerate(alphabet)}, merges=[]))
        backend.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        backend.save(str(Path(self.directory.name) / 'tokenizer.json'))
        self.tokenizer = dataset.ControlTokenizer(self.directory.name)
        self.old_ids = dict(self.tokenizer.special)
        self.finish_id = dataset.register_finish(self.tokenizer)
        self.config = json.loads((ROOT / 'configs/textturn_duplex_dataset.json').read_text())
        self.source = dict(source_id='fixture', duplicate_group='fixture',
                           texts=['How can I learn?', 'A' * 40, 'I need examples.', 'B' * 40])

    def trace(self, **settings):
        return dataset.DuplexTrace('fixture', self.tokenizer, self.source, 'train', self.config | settings)

    def start(self, trace):
        trace.user = 'How can I learn?'
        trace.step('smooth', 'start', response=self.source['texts'][1])

    def test_random_interior_pauses_are_reproducible_keep_windows(self):
        a, b = self.trace(pause_probability=1.), self.trace(pause_probability=1.)
        for trace in (a, b):
            trace.user_segment('How can I learn?', 'listen')
        self.assertEqual(a.events, b.events)
        inserted = [e for e in a.events if e['kind'] == 'pause_inserted']
        self.assertTrue(inserted)
        self.assertTrue(all(e['remaining_pieces'] > 0 and 1 <= e['windows'] <= 5 for e in inserted))
        pauses = [r for r in a.rows if r['category'] == 'pause']
        self.assertEqual(len(pauses), sum(e['windows'] for e in inserted))
        self.assertTrue(all(r['target_action'] == 'keep' and r['visible']['observation'] == dataset.SILENCE for r in pauses))
        self.assertTrue(all(b['visible_ms']-a['visible_ms'] == 160 for a, b in zip(a.rows, a.rows[1:])))

    def test_punctuation_removed_without_destroying_decimals_or_abbreviations(self):
        trace = self.trace(pause_probability=0.)
        trace.user_segment('How does it work?', 'listen')
        self.assertTrue(all(not r['visible']['user_text'].endswith('?') for r in trace.rows))
        self.assertTrue(all(not r['visible']['observation'].endswith('?') for r in trace.rows))
        trace.user = 'The value is 3.14.'
        row = trace.step('listen')
        self.assertEqual(row['visible']['user_text'], 'The value is 3.14')
        self.assertEqual(dataset.strip_terminal('Use the U.S.'), 'Use the U.S.')

    def test_uncertain_keep_then_first_decidable_update_stops(self):
        trace = self.trace()
        self.start(trace)
        trace.step('interruption', None, update=dict(text='I', version=1, turn_id=trace.turn))
        self.assertEqual(trace.state, 'Speak')
        row = trace.step('interruption', 'stop', judgment='non_backchannel',
                         update=dict(text='I meant', version=2, turn_id=trace.turn))
        self.assertEqual(row['target_action'], 'stop')
        self.assertEqual(row['stop_confirmed_ms'] - row['visible_ms'], 80)
        self.assertEqual(trace.rows[-2]['target_action'], 'keep')
        self.assertEqual(trace.state, 'Listen')
        trace.callback(trace.outputs[0]['output_id'])
        self.assertEqual(trace.events[-1]['kind'], 'stale_callback')
        trace.validate()
        failed = self.trace()
        self.start(failed)
        failed.callback(failed.active['output_id'], 'error')
        self.assertEqual(failed.outputs[0]['status'], 'error')
        self.assertFalse(any(e['kind'] == 'finish' for e in failed.events))
        failed.validate()

    def test_backchannel_replaces_one_tick_and_closes_independently(self):
        trace = self.trace(backchannel_probability=1.)
        self.start(trace)
        before = trace.now
        trace.speaking_step()
        self.assertEqual(trace.now - before, 160)
        self.assertEqual(trace.rows[-1]['target_action'], 'keep')
        while trace.backchannel_queue:
            trace.speaking_step()
        self.assertEqual(trace.user, '')
        self.assertTrue(any(h.get('kind') == 'backchannel' for h in trace.history))
        self.assertEqual(trace.state, 'Speak')
        short = self.trace(backchannel_probability=1., playback_tail_ms=160, backchannels=['Uh-huh.'])
        self.start(short)
        short.active['chunks'] = ['A']
        short.drain()
        self.assertFalse(short.backchannel_queue)
        self.assertEqual(sum(e['kind'] == 'backchannel_inserted' for e in short.events),
                         sum(e['kind'] == 'backchannel_closed' for e in short.events))

    def test_finish_is_external_single_id_masked_and_not_repeated(self):
        from tokenizers import Tokenizer
        trace = self.trace(backchannel_probability=0.)
        self.start(trace)
        with self.assertRaises(ValueError):
            trace.callback(trace.active['output_id'])
        trace.drain()
        rows = [r for r in trace.rows if self.finish_id in r['input_ids']]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['visible']['state'], 'Listen')
        self.assertTrue(all(label == -100 for token, label in zip(row['input_ids'], row['labels']) if token == self.finish_id))
        trace.step('wait')
        self.assertNotIn(self.finish_id, trace.rows[-1]['input_ids'])
        for marker, token_id in self.old_ids.items():
            self.assertEqual(self.tokenizer.encode(marker), [token_id])
        path = Path(self.directory.name) / 'saved.json'
        self.tokenizer.backend.save(str(path))
        self.assertEqual(Tokenizer.from_file(str(path)).encode(dataset.FINISH).ids, [self.finish_id])
        trace.validate()
        race = self.trace(backchannel_probability=0.)
        self.start(race)
        while not (race.active['generation_complete'] and race.active['tail_windows'] == 5):
            race.speaking_step()
        row = race.step('interruption', 'stop', judgment='non_backchannel',
                        update=dict(text='Add', version=1, turn_id=race.turn))
        self.assertEqual(row['visible']['state'], 'Listen')
        self.assertEqual(row['target_action'], 'keep')
        self.assertEqual(race.outputs[0]['status'], 'finish')
        self.assertFalse(any(e['kind'] == 'stop_requested' for e in race.events))

    def test_form_balance_stream_rate_duplicates_and_open_outputs(self):
        starts = []
        for form in ('question', 'declarative'):
            for variant in ('normal', 'interrupt'):
                timeline, rows = dataset.scenario(self.source, 'train', form, variant, self.tokenizer,
                                                  self.config | {'pause_probability': 0., 'backchannel_probability': 0.})
                starts += [r for r in rows if r['target_action'] == 'start']
                self.assertTrue(all(r['target_action'] in ('keep', 'start', 'stop') for r in rows))
        self.assertEqual(sum(r['utterance_form'] == 'declarative' for r in starts), 2)
        self.assertEqual([len(self.tokenizer.encode(p)) for p in dataset.assistant_chunks('A' * 8, self.tokenizer)], [3, 3, 2])
        trace = self.trace()
        self.start(trace)
        self.assertEqual(trace.update('Right', 1, trace.turn), 'Right')
        self.assertEqual(trace.update('Right', 2, trace.turn), '')
        self.assertEqual(trace.update('Right ', 2, trace.turn), '')
        self.assertEqual(trace.update('Right now', 3, trace.turn), 'now')
        with self.assertRaises(ValueError):
            trace.update('Rewrite', 4, trace.turn)
        with self.assertRaises(ValueError):
            trace.validate()
        self.assertTrue(trace.validate(truncated=True)['truncated'])


if __name__ == '__main__':
    unittest.main()
