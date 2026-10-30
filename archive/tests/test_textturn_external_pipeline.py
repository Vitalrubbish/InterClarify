"""Check five-token identity, causal review, terminal ownership and submission safety."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/remote'))
from textturn_candidate import TOKENS, digest, validate_candidate
from textturn_external_pipeline import Pipeline, review_cases, scheduler, write
from textturn_ultrachat_retest import DuplexReplayState
from textturn_external_score import score


class CharacterTokenizer:
    def chunks(self,text,width,**kwargs):
        return [text[i:i+width] for i in range(0,len(text),width)]
    def encode(self,text):
        return list(text)


class ExternalTests(unittest.TestCase):
    def state(self):
        events=[]
        state=DuplexReplayState({'case_id':'c','initial_state':'Speak','history':[],
                'answers':['abcdef']*2,'tail_ms':480},CharacterTokenizer(),
                {'control_ms':160,'assistant_tokens':3},lambda kind,**v:events.append({'kind':kind,**v}))
        return state,events

    def test_finish_is_playback_drained_once_and_invalidates_delayed_actions(self):
        s,events=self.state();s.advance(.32)
        self.assertEqual(s.visible,'abcdef');self.assertEqual(s.played,'abc')
        snapshot=s.snapshot('',1)
        self.assertRaises(ValueError,s.terminal,'finish',.33,s.output_id)
        s.advance(.8);s.snapshot_at=.8
        visible=s.snapshot('',1)
        self.assertEqual(visible['runtime_events'][0]['marker'],'<finish>')
        self.assertEqual(visible['played_text'],'')
        self.assertEqual(s.history[-1]['played_text'],'abcdef')
        self.assertFalse(s.apply('stop',snapshot,1,.81))
        self.assertFalse(s.terminal('finish',.82,'c:output-1'))
        self.assertEqual(s.snapshot('',1)['runtime_events'],[])
        self.assertEqual(sum(e['kind']=='finish' for e in events),1)

    def test_stop_rejects_late_finish_and_keeps_played_prefix(self):
        s,events=self.state();s.advance(.32)
        self.assertTrue(s.apply('stop',s.snapshot('',1),1,.33))
        s.advance(2.)
        self.assertFalse(s.terminal('finish',2.,'c:output-1'))
        self.assertEqual(s.history[-1]['played_text'],'abc')
        self.assertFalse(any(e['kind']=='finish' for e in events))

    def test_candidate_checks_all_five_learned_rows_and_artifact_binding(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);train=root/'train';data=root/'data';best=train/'best'
            best.mkdir(parents=True);data.mkdir()
            config=root/'config.json';write(config,{'seed':1})
            write(data/'manifest.json',{'new_token_ids':TOKENS})
            write(train/'run_manifest.json',{'config':{'seed':1},'dataset_manifest_sha256':digest(data/'manifest.json')})
            (best/'adapter_model.safetensors').write_bytes(b'fixture')
            write(train/'candidate.json',{'adapter':str(best),'adapter_sha256':digest(best/'adapter_model.safetensors'),
              'stage_completed':'full','continue_online':True,'independent_test_used':False})
            write(train/'reload_verification.json',dict.fromkeys(
              ['identical_action_scores','identical_new_token_rows','new_rows_updated'],True))
            write(train/'learning_verification.json',{'mean_loss_improved':True})
            write(train/'pilot_gate.json',{'continue_full':True})
            write(best/'adapter_config.json',{'trainable_token_indices':{'embed_tokens':list(TOKENS.values())}})
            write(best/'tokenizer_config.json',{'added_tokens_decoder':{str(i):{'content':t} for t,i in TOKENS.items()}})
            self.assertEqual(validate_candidate(train,data,config)['token_ids']['<finish>'],151673)
            write(best/'adapter_config.json',{'trainable_token_indices':{'embed_tokens':list(TOKENS.values())[:4]}})
            self.assertRaises(ValueError,validate_candidate,train,data,config)

    def test_review_requires_exact_causal_prefix_not_future_reference(self):
        m={'cases':[{'case_id':'c','updates':[{'kind':'user','turn':'u','at':1.,'text':'Please'}]}]}
        review={'entries':[{'case_id':'c','update_index':0,'turn':'u','at':1.,'prefix':'Please stop',
          'prefix_sha256':'irrelevant','judgment':'non_backchannel'}]}
        self.assertRaises(ValueError,review_cases,m,review)

    def test_no_resubmission_after_ambiguous_submission_intent(self):
        p=Pipeline.__new__(Pipeline);p.protocol={'ultrachat_run':'test'}
        p.state={'jobs':{'ultrachat':{'submission_intent':True}}}
        with patch('textturn_external_pipeline.subprocess.run') as submit:
            self.assertRaises(RuntimeError,p.submit,'ultrachat');submit.assert_not_called()
        p.state['jobs']['ultrachat']['job_id']='job-1-user'
        self.assertEqual(p.submit('ultrachat'),'job-1-user')

    def test_scheduler_does_not_treat_malformed_output_as_idle(self):
        with patch('textturn_external_pipeline.subprocess.run') as run:
            run.return_value.stdout='temporary scheduler outage'
            self.assertRaises(RuntimeError,scheduler)

    def test_unbounded_training_wait_handles_missing_startup_log_and_obeys_final_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'submit_logs').mkdir()
            p=Pipeline.__new__(Pipeline);p.root=root;p.output=root;p.deadline=None
            p.protocol={'training_run':'new-run','training_job':'job-1-user'}
            exit_path=root/'submit_logs/new-run.exit_code.txt'
            running=({'job-1-user':{'status':'Running'}},'scheduler-running')
            completed=({'job-1-user':{'status':'Completed'}},'scheduler-completed')
            with patch('textturn_external_pipeline.scheduler',side_effect=[running,completed]), \
                    patch('textturn_external_pipeline.time.time',return_value=float('inf')), \
                    patch('textturn_external_pipeline.time.sleep',side_effect=lambda _:exit_path.write_text('0')), \
                    patch('textturn_external_pipeline.subprocess.check_output',return_value='EndTime: 2026-10-27 12:00:00'), \
                    patch.object(p,'save') as save,patch.object(p,'freeze_candidate') as freeze:
                p.wait_training()
                self.assertEqual(save.call_args_list[0].args[1]['last_training_log'],[])
                freeze.assert_called_once()
            p.deadline=0
            with patch('textturn_external_pipeline.scheduler',return_value=running),patch.object(p,'save'):
                self.assertRaises(TimeoutError,p.wait_training)

    def test_natural_finish_is_not_a_successful_stop_and_unknown_stays_unknown(self):
        case={'case_id':'c','source_id':'s','mode':'clean_text_events','category':'mixed','initial_state':'Speak',
          'prefix_reviews':[{'turn':'u','prefix':'Please stop','at':.2,'judgment':'non_backchannel'}]}
        manifest={'cases':[case],'protocol':{'input_modes':['clean_text_events']},'review':{'limitations':[]}}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'traces').mkdir()
            events=[{'kind':'speak_begin','at':0.,'generation':1},
              {'kind':'user_update','at':.2,'scheduled_at':.2,'turn':'u','text':'Please stop','delta':'Please stop',
               'state':'Speak','trigger_visible':True},
              {'kind':'playback_complete','at':.4,'generation':1},
              {'kind':'case_end','at':1.5,'calls':1,'errors':[],'tail_observed':True}]
            (out/'traces/c.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            result=score(manifest,out)['clean_text_events']
            self.assertEqual(result['semantic_opportunities'],1)
            self.assertEqual(result['timely_1000'],0)
            self.assertEqual(result['natural_before_1000'],1)


if __name__=='__main__':
    unittest.main()
