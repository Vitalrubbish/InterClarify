"""Check positive whole-trajectory supervision and effective weighted gradients."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'training'))
import textturn_loss as loss
from freeze_textturn_full_trajectories import select_whole_sources
from train_textturn import register_dataset_tokens


class TextTurnLossTests(unittest.TestCase):
    def policy(self):
        return json.loads((ROOT / 'configs/textturn_full_trajectory.json').read_text())['loss_policy']

    def rows(self, identity, count):
        return [dict(scenario_id=identity, snapshot_id=f'{identity}:{i}', visible_ms=(i+1)*160,
                     visible={'state': 'Listen'}, category='pause', target_action='keep', excluded_reason=None)
                for i in range(count)]

    def test_every_frame_weighted_and_keep_mass_bounded_per_trajectory(self):
        rows = self.rows('a', 70) + self.rows('b', 3)
        loss.assign_loss_weights(rows, self.policy())
        self.assertEqual(len(rows), 73)
        self.assertTrue(all(r['loss_weight'] > 0 for r in rows))
        for group in loss.complete_trajectory_groups(rows):
            self.assertAlmostEqual(sum(r['loss_weight'] for r in group), 2.)
        positive = self.rows('start', 1)
        positive[0]['target_action'] = 'start'
        loss.assign_loss_weights(positive, self.policy())
        self.assertEqual(positive[0]['loss_weight'], 2.)

    def test_weights_change_single_sample_loss_and_gradient(self):
        import torch
        a = torch.tensor([[.2, -.1]], requires_grad=True)
        b = a.detach().clone().requires_grad_()
        target = torch.tensor([1])
        one = loss.weighted_action_loss(a, target, [1.], 1.)
        two = loss.weighted_action_loss(b, target, [2.], 1.)
        one.backward(); two.backward()
        self.assertTrue(torch.allclose(two, one*2))
        self.assertTrue(torch.allclose(b.grad, a.grad*2))
        with self.assertRaises(ValueError):
            loss.weighted_action_loss(a, target, [0.], 1.)

    def test_accumulation_matches_weighted_batch_with_fixed_normalizer(self):
        import torch
        values = torch.tensor([[.2, -.1], [-.3, .4]], requires_grad=True)
        targets = torch.tensor([0, 1])
        weights = [.1, 2.]
        combined = loss.weighted_action_loss(values, targets, weights, 1.05)
        separate = sum(loss.weighted_action_loss(values[i:i+1], targets[i:i+1], [weights[i]], 1.05)
                       for i in range(2))/2
        self.assertTrue(torch.allclose(combined, separate))

    def test_shuffle_preserves_complete_trajectory_order_and_budget_does_not_cut(self):
        rows = self.rows('a', 70) + self.rows('b', 4)
        ordered = loss.trajectory_order(rows, 42)
        self.assertEqual(len(ordered), 74)
        self.assertEqual(len(loss.complete_trajectory_groups(ordered)), 2)
        with self.assertRaises(ValueError):
            loss.complete_trajectory_groups(rows[1:])
        self.assertEqual(select_whole_sources(['a', 'b', 'c'], {'a':70,'b':40,'c':10}, 100), (['a'],70))

    def test_training_registry_includes_input_only_finish_without_changing_actions(self):
        class Tokenizer:
            def __init__(self): self.ids = {}
            def add_special_tokens(self, value):
                self.ids = {marker:151669+i for i, marker in enumerate(value['additional_special_tokens'])}
            def convert_tokens_to_ids(self, marker): return self.ids[marker]
            def encode(self, marker, add_special_tokens=False): return [self.ids[marker]]
        markers = ['<|tt_keep|>', '<|tt_start|>', '<|tt_stop|>', '<|no-voice|>', '<finish>']
        ids = register_dataset_tokens(Tokenizer(), {'new_token_ids':{marker:151669+i for i,marker in enumerate(markers)}})
        self.assertEqual(ids, [151669,151670,151671,151672,151673])


if __name__ == '__main__':
    unittest.main()
