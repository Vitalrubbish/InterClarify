"""Exercise causal boundaries and the new logical-update contract."""
from collections import Counter
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'/'training'))
from repair_textturn_dataset import (complete_prefix, anchor_visible, load_inputs, ReleaseStream,
                                     RepairTrace, rng_for, audit_row)
from textturn_input import model_visible, render_prompt
from textturn_loss import logical_groups, assign_loss_weights


class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,_,cls.tokenizer=load_inputs(ROOT/'artifacts'/'textturn'/'tt-001-frozen-r3')
        cls.config=json.loads((ROOT/'configs'/'textturn_repair.json').read_text())
        cls.phrases=json.loads((ROOT/'configs'/'textturn_transition_phrases.json').read_text())

    def test_sentence_boundary_only_uses_current_prefix(self):
        for text in ('A complete thought.', 'Is that clear?', 'Done!"', '完成。）'):
            self.assertTrue(complete_prefix(text),text)
        for text in ('Dr.', 'It costs 12.', 'Perhaps...', 'unfinished', 'U.S.', 'Done. More'):
            self.assertFalse(complete_prefix(text),text)
        self.assertFalse(anchor_visible('I mea',['i meant']))
        self.assertTrue(anchor_visible('Okay. I meant',['i meant']))

    def test_punctuation_is_an_update_and_ids_do_not_change_input(self):
        visible=dict(state='Listen',user_text='Done.',observation='.',observation_type='text-update',
                     output_id='source:normal:output-1',runtime_events=[dict(kind='finish',output_id='x',occurred_ms=12)])
        mapped=model_visible(visible)
        self.assertEqual(mapped['observation'],'')
        self.assertEqual(mapped['observation_type'],'text-update')
        changed=visible|dict(output_id='other:interrupt',user_version=100)
        self.assertEqual(render_prompt(visible),render_prompt(changed))
        self.assertNotEqual(render_prompt(visible),render_prompt(visible|dict(observation_type='empty-observation')))
        self.assertNotIn('output_id',render_prompt(visible))

    def test_release_is_lossless_and_does_not_merge_punctuation(self):
        text='A longer sentence. Another example has several words and punctuation.'
        first=ReleaseStream(text,self.tokenizer,rng_for(20261027,'release'),self.config)
        second=ReleaseStream(text,self.tokenizer,rng_for(20261027,'release'),self.config)
        self.assertEqual(list(first.queue),list(second.queue))
        self.assertEqual(''.join(first.queue),text)
        self.assertTrue(any(not t for t in first.queue))
        pieces=[t for t in first.queue if t]
        self.assertTrue(all(len(self.tokenizer.encode(t))<=2 for t in pieces))

    def test_outputs_have_independent_cursors_and_no_restart(self):
        source=dict(source_id='fixture',duplicate_group='fixture',texts=['Explain this simple example.',
                    'This is a complete response with enough words to observe generation and slower playback.'])
        trace=RepairTrace(source,0,'ordinary','train',self.tokenizer,self.config,self.phrases)
        trace.opportunity_assigned=True
        timeline,rows=trace.run()
        assign_loss_weights(rows,self.config['loss_policy'])
        for row in rows:audit_row(row,self.tokenizer)
        self.assertTrue(any(r['visible']['assistant_generation_complete'] and
                            r['visible']['played_text']!=r['visible']['assistant_visible'] for r in rows))
        starts=[e for e in timeline['events'] if e['kind']=='start_accepted']
        closed=[e for e in timeline['events'] if e['kind'] in ('stop','finish')]
        self.assertEqual(len(starts),len(closed))
        self.assertEqual(len(starts),1)
        progress=[e for e in timeline['events'] if e['kind']=='output_progress']
        cursors=[e['played_cursor'] for e in progress]
        self.assertTrue(all(b-a<=1 for a,b in zip([0]+cursors,cursors)))
        self.assertTrue(any(r['visible']['playback_phase']=='preparing' for r in rows))

    def test_stop_then_request_restarts_but_stop_only_does_not(self):
        source=dict(source_id='takeover',duplicate_group='takeover',texts=['Explain this simple example.',
                    'This complete response contains enough tokens for a user to interrupt it during playback before it reaches the end. '*4])
        outcomes={}
        for variant in ('control-request','control-stop','control-backchannel'):
            trace=RepairTrace(source,0,variant,'train',self.tokenizer,self.config,self.phrases)
            _,rows=trace.run();outcomes[variant]=Counter(r['target_action'] for r in rows)
            if variant!='control-backchannel':
                self.assertGreater(outcomes[variant]['stop'],0)
        self.assertEqual(outcomes['control-backchannel']['stop'],0)
        self.assertGreater(outcomes['control-request']['start'],outcomes['control-stop']['start'])

    def test_duplicate_transcripts_pass_through_the_only_update_entry(self):
        source=dict(source_id='dedup',duplicate_group='dedup',texts=['A request.', 'A response.'])
        trace=RepairTrace(source,0,'ordinary','train',self.tokenizer,self.config,self.phrases)
        self.assertEqual(trace.update('Okay',1,1),'Okay')
        self.assertEqual(trace.update('Okay',1,1),'')
        self.assertEqual(trace.update('Okay',0,1),'')
        self.assertEqual(trace.update('Okay. I meant',2,0),'')
        self.assertEqual(trace.user,'Okay')
        self.assertEqual(trace.update('Okay. I meant',2,1),'. I meant')

    def test_eight_actual_empty_observations_after_unmarked_user_end(self):
        source=dict(source_id='unmarked',duplicate_group='unmarked',texts=['An unfinished request', 'A response.'])
        trace=RepairTrace(source,0,'ordinary','train',self.tokenizer,self.config,self.phrases)
        _,rows=trace.run()
        last=max(i for i,r in enumerate(rows) if r['visible']['observation_type']=='text-update')
        self.assertEqual(len(rows)-last-1,8)
        self.assertTrue(all(r['target_action']=='keep' for r in rows))

    def test_opportunity_scoring_counts_early_false_actions(self):
        from train_textturn_pilot import score_opportunities
        config=json.loads((ROOT/'configs'/'textturn_repair_pilot.json').read_text())
        rows=[dict(snapshot_id='a:0',scenario_id='a',category='listen',opportunity_id='a:listen:0',
                   target_action='keep',visible={'state':'Listen'},visible_ms=160,allowed_visible_ms=160),
              dict(snapshot_id='a:1',scenario_id='a',category='smooth',opportunity_id='a:smooth:0',
                   target_action='start',visible={'state':'Listen'},utterance_form='declarative',
                   visible_ms=320,allowed_visible_ms=320)]
        good=[dict(snapshot_id=r['snapshot_id'],action=r['target_action'],control_ms=1.) for r in rows]
        self.assertEqual(score_opportunities(rows,good,config)['all']['smooth']['numerator'],1)
        bad=[dict(snapshot_id=r['snapshot_id'],action='start',control_ms=1.) for r in rows]
        self.assertEqual(score_opportunities(rows,bad,config)['all']['smooth']['numerator'],0)
        self.assertFalse(score_opportunities(rows,good,config)['all']['passed'])

    def test_logical_loss_gradient_matches_three_class_means(self):
        import torch
        rows=[]
        for i,a in enumerate(('keep','keep','start','stop')):
            rows.append(dict(source_id='one',utterance_form='question',scenario_id='trace',
                             snapshot_id=f'trace:{i}',visible_ms=(i+1)*160,excluded_reason=None,
                             target_action=a,loss_weight=[.25,.75,2.,2.][i]))
        _,windows,scales=logical_groups(rows)[0]
        logits=torch.tensor([[.2,-.1,.3]]*4,requires_grad=True)
        target=torch.tensor([0,0,1,2])
        ce=torch.nn.functional.cross_entropy(logits,target,reduction='none')
        accumulated=sum(ce[i]*scales[i] for i in range(4))
        expected=(ce[0]*.25+ce[1]*.75+ce[2]+ce[3])/3
        self.assertTrue(torch.allclose(accumulated,expected))
        ga=torch.autograd.grad(accumulated,logits,retain_graph=True)[0]
        gb=torch.autograd.grad(expected,logits)[0]
        self.assertTrue(torch.allclose(ga,gb))
        with self.assertRaises(ValueError):logical_groups(rows[:-1])


if __name__=='__main__':unittest.main()
