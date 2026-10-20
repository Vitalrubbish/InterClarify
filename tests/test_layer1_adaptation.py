"""Reject premature adaptation and inconsistent first-round comparisons."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))
import prepare_layer1_adaptation as preparation
import train_layer1 as training


class AdaptationTests(unittest.TestCase):
    def setUp(self):
        self.protocol = yaml.safe_load((ROOT / 'configs/layer1_adaptation_protocol.yaml').read_text())
        self.protocol['training_released'] = False
        self.protocol['acceptance']['sample_manifest'] = None
        self.config_path = ROOT / 'configs/layer1_adaptation_training.yaml'
        self.config = yaml.safe_load(self.config_path.read_text())
        self.index = json.loads((ROOT / self.protocol['training']['full_train_index']).read_text())

    def validate(self, root, arm='T1', **changes):
        config = {**self.config, **changes}
        preparation.validate_formal_config(config, self.protocol, root, arm, 1000, 2048, 1214)

    def release(self, root):
        self.protocol['training_released'] = True

    def test_closed_gate_fails_before_output_or_model_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'training'
            protocol = Path(tmp) / 'protocol.yaml'
            protocol.write_text(yaml.safe_dump(self.protocol))
            args = SimpleNamespace(config=self.config_path, protocol=protocol,
                                   arm='T1', dialogues=1000, length=2048, steps=1214, output=output)
            with self.assertRaisesRegex(ValueError, 'Formal training blocked'):
                training.train(args)
            self.assertFalse(output.exists())

    def test_release_flag_alone_cannot_bypass_technical_evidence(self):
        self.protocol['training_released'] = True
        self.protocol['gates']['issue001_runtime_comparison'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'issue001_runtime_comparison'):
            self.validate(ROOT)

    def test_dev_evaluator_and_content_judge_are_not_training_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            self.assertNotIn('evaluation_assets', self.protocol)
            for arm in preparation.ARMS:
                self.validate(root, arm)

    def test_test_scores_cannot_select_intermediate_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            self.protocol['training']['checkpoint_selection'] = 'best_fdb_score'
            with self.assertRaisesRegex(ValueError, 'final_epoch'):
                self.validate(root)

    def test_real_recordings_are_not_required_for_synthetic_adaptation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            for real_manifest in (None, 'not-collected-yet.json'):
                with self.subTest(real_manifest=real_manifest):
                    self.protocol['acceptance']['sample_manifest'] = real_manifest
                    self.validate(root)
                    self.assertEqual(preparation.release_blockers(self.protocol, root), [])

    def test_baseline_and_changed_optimizer_or_budget_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            with self.assertRaisesRegex(ValueError, 'B0 never trains'):
                self.validate(root, 'B0')
            for change in ({'learning_rate': 0.001}, {'warmup_steps': 2}, {'scheduler_steps': 100},
                           {'save_every_steps': 200}, {'max_wall_seconds': 28801}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.validate(root, **change)

    def test_real_index_is_comparable_and_corruption_is_rejected(self):
        preparation.validate_index(self.index, self.protocol)
        for key, value in (('manifest_sha256', 'changed'), ('length', 512), ('subset', ['duplicate'] * 1000)):
            index = copy.deepcopy(self.index)
            index['T2'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                preparation.validate_index(index, self.protocol)
        for key, value in (('view_original', 501), ('sequences', 2429), ('effective_tokens', 1193874)):
            index = copy.deepcopy(self.index)
            index['T3']['statistics'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                preparation.validate_index(index, self.protocol)

    def test_plan_does_not_train_b0_or_claim_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            protocol = Path(tmp) / 'protocol.yaml'
            protocol.write_text(yaml.safe_dump(self.protocol))
            plan = preparation.build_plan(protocol, self.config_path)
        self.assertEqual(set(plan['conditions']), {'B0', 'T1', 'T2', 'T3'})
        self.assertFalse(plan['conditions']['B0']['updates'])
        self.assertFalse(plan['training_released'])
        self.assertEqual(plan['conditions']['T3']['checkpoint_steps'], [203, 406, 609, 812, 1015, 1214])
        for arm in preparation.ARMS:
            self.assertEqual(plan['conditions'][arm]['evaluation_checkpoint_step'], 1214)
            self.assertEqual(plan['conditions'][arm]['test_input'], plan['conditions']['B0']['test_input'])
            self.assertNotIn('dev_views', plan['conditions'][arm])
        self.assertEqual(plan['post_training_evaluation']['mode'], 'prior_fdb_subset_full_chain')
        self.assertFalse(plan['post_training_evaluation']['automatic_content_quality_scorer'])

    def test_2048_rewindowing_preserves_dialogues_and_all_supervision(self):
        previous = json.loads((ROOT / 'reports/layer1_training/issue005-probe-20261020/r1/run/full_train_index.json').read_text())
        for arm in preparation.ARMS:
            for key in ('subset', 'manifest_sha256', 'audit_sha256'):
                self.assertEqual(self.index[arm][key], previous[arm][key])
            self.assertEqual(self.index[arm]['statistics']['effective_tokens'],
                             previous[arm]['statistics']['effective_tokens'])
            self.assertEqual(self.index[arm]['length'], 2048)
            self.assertEqual(self.index[arm]['statistics']['sequences'], 2428)

    def test_fdb_subset_is_frozen_and_excluded_from_training(self):
        evaluation = self.protocol['post_training_evaluation']
        path = ROOT / evaluation['sample_manifest']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), evaluation['sample_manifest_sha256'])
        manifest = json.loads(path.read_text())
        self.assertEqual((manifest['directories'], manifest['sessions']), (25, 25))
        self.assertEqual(manifest['input_variants'], ['input.wav'])
        self.assertEqual(len({s['input'] for s in manifest['samples']}), 25)
        expected = {'1', '10', '100', '101', '102'}
        for subset in ('candor_pause_handling', 'synthetic_pause_handling', 'candor_turn_taking',
                       'synthetic_user_interruption', 'icc_backchannel'):
            ids = {s['sample_id'] for s in manifest['samples'] if s['subset'] == subset}
            self.assertEqual(ids, {'0', '1', '10', '11', '12'} if subset == 'icc_backchannel' else expected)
        self.assertTrue(manifest['training_excluded'])
        self.assertIn('full_fdb', self.protocol['data']['exclusions'])

    def test_old_window_and_step_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            for length, steps in ((512, 1214), (2048, 5763), (512, 5763)):
                with self.subTest(length=length, steps=steps), self.assertRaises(ValueError):
                    preparation.validate_formal_config(self.config, self.protocol, root,
                                                       'T1', 1000, length, steps)

    def test_partial_accumulation_consumes_every_sequence_once(self):
        cursor, seen = 0, []
        while cursor < 5:
            count = training.accumulation_count(5, cursor, 2, True)
            seen.extend(range(cursor, cursor + count))
            cursor += count
        self.assertEqual(seen, list(range(5)))
        with self.assertRaisesRegex(ValueError, 'Probe exhausted'):
            training.accumulation_count(5, 4, 2, False)
        with self.assertRaises(ValueError):
            training.accumulation_count(5, 5, 2, True)


if __name__ == '__main__':
    unittest.main()
