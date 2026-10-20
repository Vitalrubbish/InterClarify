"""Check the second-round contract and weighted causal gradients against direct CE."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))
from layer1_loss import CONTROL_TOKENS, CONTROL_WEIGHTS, target_statistics, weighted_causal_loss
from prepare_layer1_adaptation import validate_alignment_config
from layer1_candidate import load_candidate
import train_layer1 as training


class AlignmentConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / 'configs/layer1_alignment_training.yaml').read_text())
        self.protocol = yaml.safe_load((ROOT / 'configs/layer1_alignment_protocol.yaml').read_text())

    def validate(self, probe=True, steps=8, **changes):
        return validate_alignment_config({**self.config, **changes}, self.protocol, ROOT,
                                         'T2', 1000, 2048, steps, probe)

    def test_only_loss_and_warmup_change(self):
        self.validate()
        self.assertEqual(self.config['learning_rate'], 2e-5)
        self.assertEqual(self.config['warmup_steps'], 122)
        for changes in ({'learning_rate': 1e-5}, {'warmup_steps': 37}, {'gradient_accumulation': 4},
                        {'purpose': 'issue006_round1'}, {'max_output_gib': 100}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(**changes)
        loss = copy.deepcopy(self.config['loss'])
        loss['control_weights']['finish'] = 1
        with self.assertRaises(ValueError):
            self.validate(loss=loss)

    def test_full_training_requires_current_resource_evidence(self):
        self.protocol['release_policy'] = 'measured_alignment_probe'
        self.protocol['training_released'] = False
        with self.assertRaisesRegex(ValueError, 'resource release pending'):
            self.validate(False, 1214)
        self.protocol['training_released'] = True
        self.protocol['resource_report_sha256'] = None
        with self.assertRaisesRegex(ValueError, 'evidence missing'):
            self.validate(False, 1214)

    def test_explicit_user_waiver_releases_only_the_frozen_formal_condition(self):
        self.validate(False, 1214)
        with self.assertRaisesRegex(ValueError, 'registered loss/warmup'):
            self.validate(False, 1214, learning_rate=1e-5)
        with self.assertRaisesRegex(ValueError, 'final epoch'):
            self.validate(False, 8)
        self.protocol['probe_waiver'] = {'decision': 'skip_every_check'}
        with self.assertRaisesRegex(ValueError, 'explicit user'):
            self.validate(False, 1214)

    def test_probe_and_scope_cannot_expand(self):
        for steps in (0, 101, 1214):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                self.validate(steps=steps)
        for arm, count, length in (('T1', 1000, 2048), ('T2', 100, 2048), ('T2', 1000, 4096)):
            with self.assertRaises(ValueError):
                validate_alignment_config(self.config, self.protocol, ROOT, arm, count, length, 8, True)
        self.protocol['parent_protocol_sha256'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'Parent protocol changed'):
            self.validate()

    def test_probe_is_rejected_by_the_serving_loader_before_loading_tensors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            identity = {'config': self.config, 'alignment_probe': True}
            (path / 'manifest.json').write_text(json.dumps({'identity': identity}))
            (path / 'summary.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'cannot be served'):
                load_candidate(None, path / 'checkpoint.pt', None, None)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Requires a tensor-enabled conda')
class WeightedLossTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        torch.manual_seed(27)
        self.ids = {token: i + 2 for i, token in enumerate(CONTROL_TOKENS.values())}
        # All five controls, ordinary body/EOS, ignored history/header/right padding.
        self.labels = torch.tensor([[-100, -100, 2, 3, 7, 8, 4, -100],
                                    [-100, 5, -100, 6, 8, -100, -100, -100]])
        self.logits = torch.randn(2, 8, 10, requires_grad=True)

    def reference(self, logits, labels):
        torch = self.torch
        target = labels[:, 1:]
        ce = torch.nn.functional.cross_entropy(logits[:, :-1].reshape(-1, 10), target.reshape(-1),
                                               ignore_index=-100, reduction='none').reshape(target.shape)
        weights = (target != -100).float()
        for name, token in CONTROL_TOKENS.items():
            weights += (target == self.ids[token]) * (CONTROL_WEIGHTS[name] - 1)
        return (ce * weights).sum() / weights.sum(), ce, weights

    def test_shift_mask_weights_diagnostics_and_chunked_gradients(self):
        torch = self.torch
        reference, ce, weights = self.reference(self.logits, self.labels)
        expected_gradient = torch.autograd.grad(reference, self.logits)[0]
        for size in (1, 3, 64):
            logits = self.logits.detach().clone().requires_grad_(True)
            total, diag = weighted_causal_loss(logits, self.labels, self.ids, CONTROL_WEIGHTS, size)
            loss = total / diag['target_weight_sum']
            loss.backward()
            torch.testing.assert_close(loss, reference)
            torch.testing.assert_close(logits.grad, expected_gradient)
            self.assertEqual(diag['effective_tokens'], 8)
            self.assertEqual(diag['target_weight_sum'], float(weights.sum()))
            self.assertAlmostEqual(diag['ordinary_nll_sum'], float(ce.detach().sum()), places=5)
            self.assertEqual(diag['control_counts'], dict.fromkeys(CONTROL_TOKENS, 1))
            for name, token in CONTROL_TOKENS.items():
                expected = float(ce.detach()[self.labels[:, 1:] == self.ids[token]].sum())
                self.assertAlmostEqual(diag['control_nll_sums'][name], expected, places=5)
            self.assertTrue(torch.equal(logits.grad[:, -1], torch.zeros_like(logits.grad[:, -1])))

    def test_accumulation_uses_global_weight_denominator(self):
        torch = self.torch
        reference, _, _ = self.reference(self.logits, self.labels)
        expected = torch.autograd.grad(reference, self.logits)[0]
        rows = [{'labels': row.tolist()} for row in self.labels]
        stats = target_statistics(rows, self.ids, CONTROL_WEIGHTS)
        logits = self.logits.detach().clone().requires_grad_(True)
        losses = []
        local_means = []
        for i in range(2):
            numerator, diag = weighted_causal_loss(logits[i:i+1], self.labels[i:i+1], self.ids,
                                                  CONTROL_WEIGHTS, 2)
            loss = numerator / stats['target_weight_sum']
            local_means.append(float(numerator.detach()) / diag['target_weight_sum'])
            losses.append(float(loss.detach()))
            loss.backward()
        self.assertAlmostEqual(sum(losses), float(reference.detach()), places=6)
        self.assertNotAlmostEqual(sum(local_means) / 2, float(reference.detach()), places=4)
        torch.testing.assert_close(logits.grad, expected)

    def test_unit_weights_equal_ordinary_ce_and_empty_targets_fail(self):
        torch = self.torch
        ones = dict.fromkeys(CONTROL_TOKENS, 1)
        numerator, diag = weighted_causal_loss(self.logits, self.labels, self.ids, ones, 2)
        expected = torch.nn.functional.cross_entropy(self.logits[:, :-1].reshape(-1, 10),
                                                     self.labels[:, 1:].reshape(-1))
        torch.testing.assert_close(numerator / diag['target_weight_sum'], expected)
        with self.assertRaisesRegex(ValueError, 'No effective'):
            weighted_causal_loss(self.logits, torch.full_like(self.labels, -100), self.ids, ones)
        with self.assertRaisesRegex(ValueError, 'No effective'):
            target_statistics([{'labels': [-100, -100]}], self.ids, ones)

    def test_resume_identity_rejects_changed_objective_before_parameter_copy(self):
        torch = self.torch
        model = torch.nn.Linear(2, 1)
        optimizer = torch.optim.AdamW(model.parameters())
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.pt'
            identity = {'loss': CONTROL_WEIGHTS, 'warmup_steps': 122}
            training.save_checkpoint(path, model, optimizer, scheduler, identity, 1, 2)
            before = training.tree_digest(model.state_dict())
            with self.assertRaisesRegex(ValueError, 'identity'):
                training.restore_checkpoint(path, model, optimizer, scheduler,
                                            {**identity, 'warmup_steps': 37})
            self.assertEqual(training.tree_digest(model.state_dict()), before)

    def test_formal_generation_probe_does_not_override_candidate_eligibility(self):
        torch = self.torch
        import layer1_candidate as candidate
        name = 'llm.base_model.model.model.layers.0.self_attn.q_proj.lora_A.default.weight'
        value = torch.nn.Parameter(torch.ones(2, 3))
        wrapper = SimpleNamespace(named_parameters=lambda: [(name, value)], requires_grad_=lambda _: None)
        model = SimpleNamespace(parameters=lambda: iter([value]), eval=lambda: None,
                                generate=lambda **kwargs: torch.tensor([[1, 2, 9]]))
        loaded = SimpleNamespace(wrapper=wrapper, model=model, token_ids={'<|im_end|>': 9})
        config = {'purpose': 'issue036_alignment', 'condition': 'T2_R2_paper_aligned',
                  'arm': 'T2', 'scheduler_steps': 1214}
        identity = {'config': config, 'alignment_probe': False, 'assets': {},
                    'data': {'statistics': {'sequences': 2428}}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'checkpoint.pt'
            torch.save({'identity': identity, 'step': 1214, 'cursor': 2428, 'lora': {name: value.detach()}}, path)
            summary = {'passed': True, 'formal_training_released': True, 'frozen_tensors_unchanged': True,
                       'final_step': 1214, 'cursor': 2428, 'checkpoint': {'sha256': candidate.sha256_file(path)},
                       'protocol_probe': {'prompt_ids': [1, 2], 'generated_ids': [9]}}
            manifest = {'identity': identity, 'formal_training_released': True,
                        'arguments': {'inventory': 'inventory', 'official_source': 'official'}}
            for file, data in [('summary.json', summary), ('manifest.json', manifest),
                               ('weights_before.json', {}), ('weights_after.json', {})]:
                (root / file).write_text(json.dumps(data))
            with patch.object(candidate, 'verify_asset_inventory', return_value={}), \
                 patch.object(candidate, 'state_fingerprints', return_value={}):
                report = candidate.load_candidate(loaded, path, root, root)
            self.assertTrue(report['inference_eligible'])
            self.assertTrue(report['clean_process_probe_ids_match'])


if __name__ == '__main__':
    unittest.main()
