"""Reject inert controllers while accepting explicitly low positive-action coverage."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))
from textturn_gate import candidate_gate, development_gate, selection_key


def metric(n, d):
    return {'numerator':n, 'denominator':d, 'rate':n/d, 'planned':d, 'unknown':0}


class DevelopmentGateTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT/'configs/textturn_full_trajectory_training.json').read_text())
        self.baseline = {'smooth':metric(0,800), 'declarative':metric(0,400),
            'interruption':metric(102,400), 'pause_false_start':metric(296,737),
            'backchannel_false_stop':metric(120,242), 'runtime':metric(88947,88947),
            'opportunity_score':.27150080177624275}
        self.inert = {**deepcopy(self.baseline), 'interruption':metric(0,400),
            'pause_false_start':metric(0,737), 'backchannel_false_stop':metric(0,242),
            'opportunity_score':.4}
        self.low = {**deepcopy(self.inert), 'smooth':metric(8,800),
                    'declarative':metric(4,400), 'interruption':metric(4,400),
                    'opportunity_score':.406}

    def test_all_keep_cannot_pass_despite_improved_score_and_no_false_actions(self):
        result = development_gate(self.baseline,self.inert,self.config)
        self.assertFalse(result['passed'])
        self.assertTrue(result['conditions']['score_improved'])
        self.assertEqual(set(result['reasons']),{'smooth_floor','declarative_floor','interruption_floor'})

    def test_exact_one_percent_is_allowed_and_one_fewer_success_fails(self):
        result = development_gate(self.baseline,self.low,self.config)
        self.assertTrue(result['passed'])
        self.assertEqual([result['positive_floors'][k]['required_successes'] for k in
                          ('smooth','declarative','interruption')],[8,4,4])
        for name in ('smooth','declarative','interruption'):
            changed=deepcopy(self.low);m=changed[name]
            changed[name]=metric(m['numerator']-1,m['denominator'])
            self.assertFalse(development_gate(self.baseline,changed,self.config)['passed'])

    def test_incomplete_unknown_nonfinite_and_false_action_regression_fail(self):
        mutations=[('runtime',metric(88946,88947)),('smooth',metric(8,799)),
            ('interruption',{**metric(4,400),'unknown':1}),('smooth',None),
            ('backchannel_false_stop',metric(126,242)),('opportunity_score',float('nan'))]
        for name,value in mutations:
            with self.subTest(name=name,value=value):
                changed=deepcopy(self.low);changed[name]=value
                self.assertFalse(development_gate(self.baseline,changed,self.config)['passed'])

    def test_qualified_candidate_outranks_inert_score_and_full_is_selected(self):
        bad={'stage':'full','dev':{**self.inert,'opportunity_score':.9}}
        pilot={'stage':'pilot','dev':self.low}
        full={'stage':'full','dev':{**self.low,'opportunity_score':.405}}
        key=lambda r:selection_key(r,self.baseline,self.config)
        self.assertGreater(key(pilot),key(bad))
        self.assertGreater(key(full),key(pilot))
        self.assertTrue(candidate_gate(self.baseline,full,self.config,'full')['passed'])
        self.assertFalse(candidate_gate(self.baseline,pilot,self.config,'full')['passed'])
        self.assertFalse(candidate_gate(self.baseline,bad,self.config,'full')['passed'])

    def test_legacy_config_preserves_old_score_selection_without_new_floors(self):
        config={k:v for k,v in self.config.items() if k!='development_gate'}
        self.assertTrue(development_gate(self.baseline,self.inert,config)['passed'])
        self.assertEqual(selection_key({'dev':self.inert},self.baseline,config),(.4,))


if __name__=='__main__':
    unittest.main()
