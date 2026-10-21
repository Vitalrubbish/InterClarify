"""Check strict checkpoint mapping and the exact existing-LoRA whitelist on CPU fakes."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
import layer1_model as model


class Tensor:
    def __init__(self, shape=(2, 3)):
        self.shape, self.dtype, self.requires_grad = shape, 'bfloat16', False

    def numel(self):
        result = 1
        for n in self.shape:
            result *= n
        return result

    def requires_grad_(self, value):
        self.requires_grad = value


class Wrapper:
    def __init__(self, state):
        self.state = state
        self.loaded = None

    def state_dict(self):
        return self.state

    def load_state_dict(self, state, strict):
        if not strict:
            raise AssertionError('strict is required')
        self.loaded = state

    def requires_grad_(self, value):
        for item in self.state.values():
            item.requires_grad_(value)

    def named_parameters(self):
        return self.state.items()


class LoadingTests(unittest.TestCase):
    def test_strict_mapping_keeps_every_tensor_and_reports_shapes(self):
        source = 'llm.base_model.model.model.layers.0.self_attn.q_proj.weight'
        target = source.replace('q_proj.weight', 'q_proj.base_layer.weight')
        tensor = Tensor()
        wrapper = Wrapper({target: Tensor()})
        report = model.restore_state(wrapper, {source: tensor})
        self.assertIs(wrapper.loaded[target], tensor)
        self.assertEqual(report['mapping'][0]['source'], source)
        self.assertEqual(report['shape_mismatches'], [])

    def test_missing_extra_collision_and_shape_are_rejected_before_copy(self):
        target = 'llm.base_model.model.model.layers.0.self_attn.v_proj.base_layer.weight'
        source = target.replace('.base_layer', '')
        for state in ({}, {'extra': Tensor()}, {source: Tensor(), target: Tensor()}, {source: Tensor((1,))}):
            wrapper = Wrapper({target: Tensor()})
            with self.assertRaises(ValueError):
                model.restore_state(wrapper, state)
            self.assertIsNone(wrapper.loaded)

    def test_only_complete_existing_qv_default_adapter_is_trainable(self):
        state = {}
        for layer in range(2):
            for projection in ('q_proj', 'v_proj'):
                for part in ('A', 'B'):
                    state[f'llm.base_model.model.model.layers.{layer}.self_attn.{projection}.lora_{part}.default.weight'] = Tensor()
        frozen = ['llm.base_model.model.model.embed_tokens.modules_to_save.default.weight',
                  'llm.base_model.model.lm_head.modules_to_save.default.weight',
                  'llm.base_model.model.model.layers.0.self_attn.k_proj.lora_A.default.weight',
                  'llm.base_model.model.model.layers.0.self_attn.q_proj.lora_A.other.weight']
        state.update({name: Tensor() for name in frozen})
        wrapper = Wrapper(state)
        report = model.configure_trainable(wrapper, 2)
        self.assertEqual(report['tensors'], 8)
        self.assertEqual(report['numel'], 48)
        self.assertTrue(all(not state[name].requires_grad for name in frozen))
        state.pop(report['parameters'][0]['name'])
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            model.configure_trainable(wrapper, 2)
        self.assertTrue(all(not p.requires_grad for p in state.values()))

    def test_inventory_digest_and_unsafe_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'file').write_bytes(b'published')
            entry = {'bytes': 9, 'sha256': model.sha256_file(root / 'file')}
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'assets': {name: {'files': {'file': entry}}
                                                         for name in ('checkpoint', 'base')}}))
            self.assertEqual(len(model.verify_asset_inventory(inventory, root, root)['files']), 2)
            (root / 'file').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'content mismatch'):
                model.verify_asset_inventory(inventory, root, root)


@unittest.skipUnless(importlib.util.find_spec('torch'),
                     'Real tensor tests run in the remote conda environment')
class TensorLoadingTests(unittest.TestCase):
    def test_tensor_hashes_detect_frozen_parameter_change(self):
        import torch
        wrapper = torch.nn.Linear(3, 2, dtype=torch.bfloat16)
        before = model.state_fingerprints(wrapper, block_elements=2)
        with torch.no_grad():
            wrapper.weight[0, 0] += 1
        self.assertNotEqual(before, model.state_fingerprints(wrapper, block_elements=2))


if __name__ == '__main__':
    unittest.main()
