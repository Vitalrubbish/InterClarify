"""Check causal publication, turn commits, stale actions and duration scoring."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

SPEC = importlib.util.spec_from_file_location('retest', Path(__file__).parents[1] /
                                              'scripts/remote/textturn_ultrachat_retest.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class CharacterTokenizer:
    def chunks(self, text, width, **kwargs):
        return [text[i:i+width] for i in range(0, len(text), width)]

    def encode(self, text):
        return list(text)


class RetestTests(unittest.TestCase):
    def test_real_clock_pending_calls_do_not_control_prefix_publication(self):
        case = {'case_id':'c', 'source_id':'s', 'mode':'clean_text_events', 'category':'mixed',
                'initial_state':'Speak', 'history':[], 'answers':['abcdefghijklmnopqrstuvwxyz']*2,
                'tail_ms':480, 'steps':[.16,.32,.48,.64], 'updates':[], 'duration':.64}
        def decide(visible):
            time.sleep(.4)
            return {'action':'keep'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.jsonl'
            result=m.replay_case(case, {'control_ms':160,'assistant_tokens':3},
                                 CharacterTokenizer(), decide, path)
            events=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertTrue(result['runtime_success'])
            self.assertGreaterEqual(result['merged_windows'],1)
            publications=[e for e in events if e['kind']=='assistant_publish']
            self.assertGreater(len(publications),result['control_calls'])
            self.assertEqual([e['visible'] for e in publications[:3]], ['abc','abcdef','abcdefghi'])

    def state(self, initial='Speak'):
        self.events = []
        case = {'initial_state': initial, 'history': [], 'answers': ['abcdefghij', 'klmnop'], 'tail_ms': 480}
        return m.ReplayState(case, CharacterTokenizer(), {'control_ms': 160, 'assistant_tokens': 3},
                             lambda kind, **value: self.events.append({'kind': kind, **value}))

    def test_publication_follows_time_and_stop_preserves_only_published_history(self):
        state = self.state()
        self.assertEqual(state.visible, '')
        state.advance(.49)
        self.assertEqual(state.visible, 'abcdefghi')
        self.assertEqual([e['scheduled_at'] for e in self.events if e['kind']=='assistant_publish'],
                         [.16, .32, .48])
        snapshot = state.snapshot('', 3)
        state.apply('stop', snapshot, state.generation, .5)
        state.advance(2.)
        self.assertEqual(state.history[-1]['text'], 'abcdefghi')
        self.assertTrue(state.history[-1]['interrupted'])
        self.assertEqual(state.state, 'Listen')

    def test_start_commits_request_prefix_and_leaves_new_suffix_as_current_user(self):
        state = self.state('Listen')
        event = {'kind':'user','turn':'u0','text':'Hello.','version':1,'category':'smooth','answer':1,'at':0.}
        state.update(event, 0.)
        snapshot = state.snapshot('Hello.',1)
        state.update({**event,'text':'Hello. More','version':2},.01)
        state.apply('start',snapshot,0,.02,'u0',6)
        self.assertEqual(state.history[0], {'role':'user','text':'Hello.'})
        self.assertEqual(state.snapshot(' More',1)['user_text'],' More')
        self.assertEqual(state.visible,'')

    def test_natural_completion_rejects_delayed_stop_without_fabricating_stop(self):
        state = self.state()
        state.advance(.64)
        snapshot = state.snapshot('',1)
        state.advance(1.13)
        self.assertEqual(state.state,'Listen')
        self.assertFalse(state.apply('stop',snapshot,1,1.14))
        self.assertEqual(sum(e['kind']=='stop_applied' for e in self.events),0)
        self.assertEqual(state.history[-1]['text'],'abcdefghij')

    def test_overlap_uses_first_last_update_and_strict_threshold(self):
        case={'case_id':'c','source_id':'s','mode':'recorded_online_asr','category':'interruption','initial_state':'Speak'}
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'trace.jsonl'
            events=[{'kind':'user_update','at':0.,'turn':'u','delta':'a','state':'Speak','trigger_visible':False},
                    {'kind':'user_update','at':.96,'turn':'u','delta':'b','state':'Speak','trigger_visible':True},
                    {'kind':'case_end','at':3.,'calls':1,'errors':[],'tail_observed':False}]
            p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            score=m.score_case(case,p)
            self.assertEqual(score['overlap_gt_960'],0)
            events[1]['at']=.961
            p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            self.assertEqual(m.score_case(case,p)['overlap_gt_960'],1)
            self.assertEqual(score['opportunities'],1)
            self.assertEqual(score['stop_count'],0)


if __name__ == '__main__':
    unittest.main()
