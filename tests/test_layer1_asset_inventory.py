"""Check inventory failures and tensor evidence without downloading weights."""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'scripts/remote/inventory_layer1_assets.py'
spec = importlib.util.spec_from_file_location('layer1_inventory', SCRIPT)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class AssetInventoryTests(unittest.TestCase):
    """Ensure missing assets cannot silently become successful evidence."""

    def test_tensor_header_and_full_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.safetensors'
            header = json.dumps({'q.lora_A': {'dtype': 'BF16', 'shape': [1], 'data_offsets': [0, 2]}}).encode()
            data = struct.pack('<Q', len(header)) + header + b'\0\0'
            path.write_bytes(data)
            result = inventory.file_record(path)
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(result['tensors']['q.lora_A']['shape'], [1])

    def test_invalid_header_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.safetensors'
            path.write_bytes(struct.pack('<Q', 1000))
            with self.assertRaises(ValueError):
                inventory.file_record(path)

    def test_empty_and_broken_link_are_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertTrue(inventory.asset_record(root)['errors'])
            (root / 'missing').symlink_to(root / 'absent')
            result = inventory.asset_record(root)
            self.assertTrue(any(error['path'] == 'missing' for error in result['errors']))

    def test_cli_retains_failure_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'run'
            command = [sys.executable, str(SCRIPT), '--repo', str(root), '--xtalk', str(root),
                       '--asset', f'missing={root / "absent"}', '--output', str(output)]
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(result.returncode, 1)
            report = json.loads((output / 'inventory.json').read_text())
            self.assertFalse(report['training_released'])
            self.assertEqual(len(report['errors']), 3)
            original = (output / 'inventory.json').read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual((output / 'inventory.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
