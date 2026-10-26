"""Check diagnostic action masking and deterministic evaluation selection."""
import importlib.util
from pathlib import Path
import unittest

import torch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('diagnostics', ROOT/'scripts/analysis/diagnose_textturn_training.py')
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTICS)


class TrainingDiagnosticsTests(unittest.TestCase):
    def test_legal_loss_excludes_irrelevant_vocabulary_and_rejects_illegal_targets(self):
        scores = torch.tensor([.2, -.4, .7, 100.], requires_grad=True)
        row = dict(target_action='start', visible={'state': 'Listen'})
        actual = DIAGNOSTICS.action_loss(scores, row, [0, 1, 2], 'legal')
        expected = torch.nn.functional.cross_entropy(scores[:2][None], torch.tensor([1]))
        self.assertTrue(torch.allclose(actual, expected))
        actual.backward()
        self.assertEqual(scores.grad[2:].tolist(), [0., 0.])
        with self.assertRaises(ValueError):
            DIAGNOSTICS.action_loss(scores, row | {'target_action': 'stop'}, [0, 1, 2], 'legal')

    def test_probe_keeps_all_selected_positives_and_their_own_trajectory_boundaries(self):
        rows = [dict(source_id=s, scenario_id=s, snapshot_id=f'{s}:{i}',
                     target_action='start' if i == 4 else 'keep', visible={'state': 'Listen'}, category='listen')
                for s in ('a', 'b', 'c') for i in range(10)]
        probe = DIAGNOSTICS.select_probe(rows, 7, source_count=1, keep_per_bucket=0)
        self.assertEqual([int(r['snapshot_id'].split(':')[1]) for r in probe], [2, 3, 4, 5, 6])
        self.assertEqual(len({r['source_id'] for r in probe}), 1)
        self.assertEqual(probe, DIAGNOSTICS.select_probe(rows, 7, source_count=1, keep_per_bucket=0))
        self.assertEqual(sum(r['target_action']=='start' for r in rows), 3)

    def test_gradient_measurement_preserves_unclipped_gradients_and_stops_nonfinite_values(self):
        model = torch.nn.Linear(2, 1, bias=False)
        model.weight.grad = torch.tensor([[3., 4.]])
        self.assertAlmostEqual(DIAGNOSTICS.gradient_norm(model), 5.)
        self.assertEqual(model.weight.grad.tolist(), [[3., 4.]])
        self.assertAlmostEqual(DIAGNOSTICS.gradient_norm(model, 1.), 5.)
        self.assertAlmostEqual(float(model.weight.grad.norm()), 1., places=5)
        model.weight.grad.fill_(float('nan'))
        with self.assertRaises(RuntimeError):
            DIAGNOSTICS.gradient_norm(model)


if __name__ == '__main__':
    unittest.main()
