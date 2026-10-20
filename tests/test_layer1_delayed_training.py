"""Reject stale data, truncated epochs and objective changes in delayed training."""

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))

from layer1_model import sha256_file
from prepare_layer1_adaptation import validate_delayed_config


class DelayedTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = yaml.safe_load((ROOT / 'configs/layer1_delayed_training.yaml').read_text())
        self.protocol = yaml.safe_load((ROOT / 'configs/layer1_delayed_protocol.yaml').read_text())
        for name in (self.protocol['parent_protocol'], 'configs/layer1_alignment_training.yaml',
                     'reports/layer1_training/issue040-delayed-start-data-20261020/audit.json'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        index = json.loads((ROOT / 'reports/layer1_training/issue029-window2048-20261020/full_train_index.json').read_text())
        for row in index.values():
            row['manifest_sha256'] = self.protocol['data_manifest_sha256']
            row['audit_sha256'] = self.protocol['data_audit_sha256']
            row['statistics'].update(sequences=2469, effective_tokens=1201531)
        self.index = self.root / self.protocol['training']['full_train_index']
        self.index.parent.mkdir(parents=True, exist_ok=True)
        self.index.write_text(json.dumps(index))
        self.protocol['full_train_index_sha256'] = sha256_file(self.index)

    def validate(self, steps=1235):
        return validate_delayed_config(self.config, self.protocol, self.root, 'T2', 1000, 2048, steps)

    def test_full_weighted_epoch_is_released(self):
        result = self.validate()
        self.assertEqual(result['training']['actual_steps'], 1235)
        self.assertEqual(self.config['warmup_steps'], 124)
        self.assertEqual(self.config['loss']['control_weights']['finish'], 10)

    def test_partial_epoch_and_old_authorization_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'full single T2 epoch'):
            self.validate(8)
        self.protocol['authorization']['additional_epochs'] = 2
        with self.assertRaisesRegex(ValueError, 'authorization'):
            self.validate()

    def test_ordinary_loss_and_changed_weights_are_rejected(self):
        for objective in ({'type': 'ordinary_ce'}, {'type': 'control_weighted_ce', 'control_weights': {}}):
            with self.subTest(objective=objective):
                original = self.config['loss']
                self.config['loss'] = objective
                with self.assertRaisesRegex(ValueError, 'frozen weighted configuration'):
                    self.validate()
                self.config['loss'] = original

    def test_changed_audit_and_stale_index_are_rejected(self):
        original = self.protocol['data_audit_sha256']
        self.protocol['data_audit_sha256'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'audit changed'):
            self.validate()
        self.protocol['data_audit_sha256'] = original
        index = json.loads(self.index.read_text())
        for row in index.values():
            row['manifest_sha256'] = 'old-r5'
        self.index.write_text(json.dumps(index))
        self.protocol['full_train_index_sha256'] = sha256_file(self.index)
        with self.assertRaisesRegex(ValueError, 'older dataset'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
