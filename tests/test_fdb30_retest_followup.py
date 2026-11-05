"""Keep failed smoke evidence and active jobs from launching new GPU stages."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/remote'))
from fdb30_retest_followup import Campaign, MANIFEST_SHA256, audit_run


class FollowupTests(unittest.TestCase):
    def fixture(self, root):
        execution = {'cpu_threads': 2, 'interop_threads': 1, 'sensevoice_ncpu': 2,
                     'skip_complete_recognition': True, 'thread_ident': 100, 'thread_native_id': 101}
        report = {'passed': True, 'manifest_sha256': MANIFEST_SHA256, 'scope': 'smoke',
                  'execution': execution, 'x2_execution': execution,
                  'warmup': {'passed': True, 'equivalence': {'passed': True,
                      'comparison_policy': 'control_equivalence_skip_complete_asr', 'authorized_omissions': 1}},
                  'cases': [{'passed': True, 'case_id': f'case-{i}', 'subset': 'sample', 'id': str(i),
                             'recording': {}, 'frames': 1} for i in range(1, 4)]}
        frame = {'step_id': 0, 'controller_main_lag_ms': 250., 'receipts': {'controller': {
            'execution_thread': {'ident': 100, 'native_id': 101, 'cpu_threads': 2, 'interop_threads': 1},
            'events': [{'kind': 'complete_recognition_skipped'}],
            'skip_complete_recognition': True, 'service_completion_source': 'model_complete', 'service_text': ''}}}
        for case in report['cases']:
            folder = root/'frontend/samples/sample'/case['id']
            folder.mkdir(parents=True)
            with gzip.open(folder/(case['case_id']+'.frames.jsonl.gz'), 'wt') as stream:
                stream.write(json.dumps(frame)+'\n')
        for name in ('qwen', 'indextts'):
            (root/name).mkdir()
            (root/name/'ready.json').write_text(json.dumps(execution))
        return report, frame, root/'frontend/samples/sample/1'

    def test_audit_rejects_thread_budget_and_recognition_regressions(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            report, original, folder = self.fixture(run)
            for condition in ('valid', 'thread', 'budget', 'recognition'):
                frame = deepcopy(original)
                control = frame['receipts']['controller']
                if condition == 'thread':
                    control['execution_thread']['ident'] = 999
                elif condition == 'budget':
                    control['execution_thread']['cpu_threads'] = 4
                elif condition == 'recognition':
                    control['events'] = []
                (run/'frontend/result.json').write_text(json.dumps(report))
                with gzip.open(folder/'case-1.frames.jsonl.gz', 'wt') as stream:
                    stream.write(json.dumps(frame)+'\n')
                with patch('score_duplex.validate_recording') as recording:
                    if condition == 'valid':
                        self.assertTrue(audit_run(run, 3, ROOT)['passed'])
                        self.assertEqual(recording.call_count, 3)
                    else:
                        with self.assertRaises(ValueError):
                            audit_run(run, 3, ROOT)

    def test_submission_refuses_active_jobs_and_reuses_saved_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(output=root, source=ROOT, smoke_job='job-1-test', prefix='test', root=root)
            campaign = Campaign(args)
            with patch.object(campaign, 'active', return_value={'job-2-other'}), \
                    patch('fdb30_retest_followup.subprocess.run') as submit:
                with self.assertRaisesRegex(RuntimeError, 'overlapping'):
                    campaign.submit('formal', 'true', gpus=3, cpus=12, memory='64G', output=root/'run')
                submit.assert_not_called()
            campaign.state['formal_job'] = 'job-3-existing'
            with patch('fdb30_retest_followup.subprocess.run') as submit:
                self.assertEqual(campaign.submit('formal', 'true', gpus=3, cpus=12,
                                                memory='64G', output=root/'run'), 'job-3-existing')
                submit.assert_not_called()

    def test_failed_or_missing_exit_marker_blocks_followup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(output=root, source=ROOT, smoke_job='job-1-test')
            campaign = Campaign(args)
            marker = root/'exit.txt'
            with patch.object(campaign, 'active', return_value=set()):
                with self.assertRaises(RuntimeError):
                    campaign.wait('job-1-test', marker)
                marker.write_text('1\n')
                with self.assertRaises(RuntimeError):
                    campaign.wait('job-1-test', marker)
                marker.write_text('0\n')
                campaign.wait('job-1-test', marker)


if __name__ == '__main__':
    unittest.main()
