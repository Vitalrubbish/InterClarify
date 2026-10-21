"""Reject stale ASR evidence, wrong views and changed optimization targets."""

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
from prepare_layer1_adaptation import EXPECTED_DELAYED_CONFIG, validate_delayed_config


class AsrTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        parent = 'configs/layer1_adaptation_protocol.yaml'
        (self.root / 'configs').mkdir()
        shutil.copyfile(ROOT / parent, self.root / parent)
        training = dict(arm='ASR', full_train_index='index.json', sequence_length=2048,
                        round1_sequences_per_condition=3, round1_effective_tokens_per_condition=30,
                        effective_batch=2, actual_steps=2, checkpoint_selection='final_epoch')
        self.protocol = dict(schema_version=1, issue='078', condition='ASR_R4_delayed_punctuation',
            training_released=True, parent_protocol=parent, parent_protocol_sha256=sha256_file(self.root / parent),
            data_manifest_sha256='new-data', training=training,
            authorization=dict(date='2026-10-21', decision='train_rebuilt_original_1k_asr_surface',
                               epochs=1, human_review='pending_not_claimed_passed', agent_review='completed'),
            resources=dict(gpus=1, cpus=8, memory_gib=32, workers=0, concurrent_jobs=1,
                           max_wall_seconds=28800, training_output_gib=5, total_output_gib=6, min_free_gib=20))
        self.config = copy.deepcopy(EXPECTED_DELAYED_CONFIG)
        self.config.update(purpose='issue078_asr_punctuation', condition='ASR_R4_delayed_punctuation',
                           scheduler_steps=2, warmup_steps=1, save_every_steps=1, min_free_gib=20)
        audit = dict(machine_passed=True, response_start_timing='next_no_voice', manifest_sha256='new-data',
                     asr_surface={'version': 'delayed_punctuation_v1'})
        self.save('data_audit', audit)
        index = {'ASR': dict(arm='ASR', subset=[str(i) for i in range(1000)], length=2048,
                 statistics=dict(sequences=3, effective_tokens=30, view_asr_delayed=1000),
                 manifest_sha256='new-data', audit_sha256=self.protocol['data_audit_sha256'])}
        (self.root / 'index.json').write_text(json.dumps(index))
        self.protocol['full_train_index_sha256'] = sha256_file(self.root / 'index.json')
        summary = dict(manifest_sha256='new-data', original_events_and_targets_unchanged=True,
             selected_sha256='98fe4d085a8258566f3e08eeee119f324b5708eb68b4a31f5f4de2d82a75f401',
             index_sha256=self.protocol['full_train_index_sha256'])
        self.save('data_summary', summary)
        self.save('agent_review', dict(completed=True, human_review_complete=False,
             review_type='agent_semantic_reading', manifest_sha256='new-data',
             rows=[dict(dialogue_id=str(i), turn=0, accepted=True) for i in range(60)]))

    def save(self, name, data):
        path = self.root / (name + '.json')
        path.write_text(json.dumps(data))
        self.protocol[name] = path.name
        self.protocol[name + '_sha256'] = sha256_file(path)

    def validate(self, arm='ASR', steps=2):
        return validate_delayed_config(self.config, self.protocol, self.root, arm, 1000, 2048, steps)

    def test_full_asr_epoch_accepts_pending_human_status_without_claiming_it_passed(self):
        result = self.validate()
        self.assertEqual(result['training']['arm'], 'ASR')
        self.assertFalse(result['post_training_evaluation']['automatic_submit'])

    def test_wrong_arm_partial_epoch_and_changed_loss_fail(self):
        with self.assertRaises(ValueError):
            self.validate(arm='T2')
        with self.assertRaises(ValueError):
            self.validate(steps=1)
        self.config['loss']['control_weights']['finish'] = 1
        with self.assertRaises(ValueError):
            self.validate()

    def test_stale_view_and_source_split_fail_even_with_updated_evidence_hash(self):
        path = self.root / self.protocol['data_summary']
        summary = json.loads(path.read_text())
        summary['selected_sha256'] = 'different-1k'
        self.save('data_summary', summary)
        with self.assertRaises(ValueError):
            self.validate()

    def test_old_review_and_false_human_signoff_fail(self):
        path = self.root / self.protocol['agent_review']
        review = json.loads(path.read_text())
        review['manifest_sha256'] = 'old-data'
        self.save('agent_review', review)
        with self.assertRaises(ValueError):
            self.validate()
        review.update(manifest_sha256='new-data', human_review_complete=True)
        self.save('agent_review', review)
        with self.assertRaises(ValueError):
            self.validate()

    def test_changed_authorization_or_unfrozen_evidence_fail(self):
        self.protocol['authorization']['epochs'] = 2
        with self.assertRaises(ValueError):
            self.validate()
        self.protocol['authorization']['epochs'] = 1
        (self.root / self.protocol['data_audit']).write_text('{}')
        with self.assertRaises(ValueError):
            self.validate()


if __name__ == '__main__':
    unittest.main()
