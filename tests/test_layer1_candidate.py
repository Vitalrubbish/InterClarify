"""Reject incomplete adapters and altered frozen FDB inputs before inference."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
sys.path.insert(0, str(ROOT / 'scripts/remote'))
from layer1_candidate import validate_lora
from layer1_fdb import prepare


class CandidateTests(unittest.TestCase):
    def test_exact_qv_whitelist_shape_and_dtype_are_required(self):
        name = 'llm.base_model.model.model.layers.0.self_attn.q_proj.lora_A.default.weight'
        value = SimpleNamespace(shape=(2, 3), dtype='bfloat16')
        parameters = {name: value, 'frozen.weight': value}
        validate_lora(parameters, {name: value})
        for supplied in ({}, {name: value, 'frozen.weight': value},
                         {name: SimpleNamespace(shape=(3, 2), dtype='bfloat16')},
                         {name: SimpleNamespace(shape=(2, 3), dtype='float32')}):
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                validate_lora(parameters, supplied)

    def fixture(self, root):
        source = root / 'source'
        samples = []
        for number in range(25):
            name = f'subset/{number}/input.wav'
            path = source / name
            path.parent.mkdir(parents=True)
            raw = b'frozen audio' + bytes([number])
            path.write_bytes(raw)
            samples.append({'input': name, 'files': {'input.wav': {
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}})
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({'sessions': 25, 'samples': samples, 'remote_root': str(source)}))
        return manifest

    def test_staging_keeps_exactly_the_frozen_inputs_and_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            result = prepare(manifest, root / 'out')
            self.assertEqual(result['sessions'], 25)
            self.assertEqual(len(list((root / 'out').rglob('input.wav'))), 25)
            with self.assertRaises(FileExistsError):
                prepare(manifest, root / 'out')

    def test_altered_audio_is_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            (root / 'source/subset/0/input.wav').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                prepare(manifest, root / 'out')
            self.assertFalse((root / 'out').exists())

    def test_duplicate_and_unsafe_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            original = json.loads(manifest.read_text())
            duplicate = json.loads(manifest.read_text())
            duplicate['samples'][1] = duplicate['samples'][0]
            manifest.write_text(json.dumps(duplicate))
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                prepare(manifest, root / 'duplicate')
            original['samples'][0]['input'] = '../input.wav'
            manifest.write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                prepare(manifest, root / 'unsafe')


if __name__ == '__main__':
    unittest.main()
