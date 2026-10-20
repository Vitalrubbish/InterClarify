"""Reject premature adaptation and inconsistent first-round comparisons."""

import copy
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
        self.protocol['gates']['issue007_pretraining_preparation'] = 'pending'
        self.protocol['evaluation_assets'] = dict.fromkeys(('sample_manifest', 'acceptance_config', 'evaluator'))
        self.protocol['acceptance']['sample_manifest'] = None
        self.config_path = ROOT / 'configs/layer1_adaptation_training.yaml'
        self.config = yaml.safe_load(self.config_path.read_text())
        self.index = json.loads((ROOT / self.protocol['training']['full_train_index']).read_text())

    def validate(self, root, arm='T1', **changes):
        config = {**self.config, **changes}
        preparation.validate_formal_config(config, self.protocol, root, arm, 1000, 512, 5763)

    def release(self, root):
        self.protocol['training_released'] = True
        self.protocol['gates']['issue007_pretraining_preparation'] = 'passed'
        for key in ('sample_manifest', 'acceptance_config', 'evaluator'):
            path = root / (key + '.fixture')
            path.write_text('fixture for ' + key)
            self.protocol['evaluation_assets'][key] = {'path': path.name,
                                                       'sha256': preparation.sha256_file(path)}
        self.protocol['acceptance']['sample_manifest'] = 'sample_manifest.fixture'

    def test_closed_gate_fails_before_output_or_model_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'training'
            protocol = Path(tmp) / 'protocol.yaml'
            protocol.write_text(yaml.safe_dump(self.protocol))
            args = SimpleNamespace(config=self.config_path, protocol=protocol,
                                   arm='T1', dialogues=1000, length=512, steps=5763, output=output)
            with self.assertRaisesRegex(ValueError, 'Formal training blocked'):
                training.train(args)
            self.assertFalse(output.exists())

    def test_release_flag_alone_cannot_bypass_evaluation_assets(self):
        self.protocol['training_released'] = True
        with self.assertRaisesRegex(ValueError, 'issue007_pretraining_preparation'):
            self.validate(ROOT)

    def test_frozen_assets_are_verified_and_test_acceptance_is_not_a_training_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            for arm in preparation.ARMS:
                self.validate(root, arm)
            (root / 'evaluator.fixture').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                self.validate(root)

    def test_missing_or_disagreeing_sample_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.release(root)
            self.protocol['acceptance']['sample_manifest'] = 'another.fixture'
            with self.assertRaisesRegex(ValueError, 'references disagree'):
                self.validate(root)
            (root / 'sample_manifest.fixture').unlink()
            self.assertTrue(preparation.release_blockers(self.protocol, root))

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
        for key, value in (('manifest_sha256', 'changed'), ('length', 2048), ('subset', ['duplicate'] * 1000)):
            index = copy.deepcopy(self.index)
            index['T2'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                preparation.validate_index(index, self.protocol)
        for key, value in (('view_original', 501), ('sequences', 11527), ('effective_tokens', 1193874)):
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
        self.assertEqual(plan['conditions']['T3']['checkpoint_steps'], [1000, 2000, 3000, 4000, 5000, 5763])

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
