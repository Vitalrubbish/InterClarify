"""Check decomposition accounting and missing-data semantics."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('latency_validation',
    Path(__file__).parents[1] / 'scripts/remote/latency_validation.py')
latency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(latency)


class LatencyBreakdownTests(unittest.TestCase):
    """Keep exact identities and sum stages only on the same response."""

    def test_missing_values_are_not_zero_samples(self):
        self.assertEqual(latency.stats([None, 1, 3])['mean'], 2)
        self.assertEqual(latency.stats([])['n'], 0)

    def test_response_milestones_add_to_total(self):
        report = {'session_id':'s','client_origin_monotonic':100,'input_start_seconds':0,
            'input_audio_seconds':5,'client_measurements':{'responses':[{'response_id':'r'}],
            'anchors':{'turn_taking':1}}, 'events':[
                {'action':'pcm_received','seconds':2.2,'data':{'response_id':'r'}},
                {'action':'audible_proxy','seconds':2.3,'data':{'response_id':'r','audible_monotonic':102.25}}]}
        def event(kind, t, **fields):
            return {'event_type':kind,'monotonic_timestamp':t,'text':'hi','response_id':'',
                    'request_id':'q',**fields}
        timeline = [event('asr.result_partial',101.1),event('duplex.micro_turn_ready',101.2),
                    event('duplex.protocol_parsed',101.5)]
        diagnostics = [dict(source='latency_answer',response_id='r',request_id='q',at_monotonic=101.6),
            dict(source='latency_tts',response_id='r',kind='request',at_monotonic=101.9),
            dict(source='latency_tts',response_id='r',kind='pcm',at_monotonic=102.1,compute_seconds=.19)]
        models = [dict(session_id='s',request_id='q',model_started_monotonic=101.3,seconds=.4)]
        row = latency.response_rows(report,timeline,diagnostics,models)[0]
        self.assertAlmostEqual(row['total_audible_seconds'],1.25)
        self.assertAlmostEqual(row['decomposition_residual_seconds'],0)
        self.assertAlmostEqual(row['model_first_control_seconds'],.2)
        self.assertAlmostEqual(row['parts_seconds']['model_started_to_first_text'],.3)
        missing = latency.response_rows(report,timeline[1:],diagnostics,models)[0]
        self.assertIsNone(missing['parts_seconds']['anchor_to_asr_visible'])
        self.assertIsNone(missing['decomposition_residual_seconds'])
