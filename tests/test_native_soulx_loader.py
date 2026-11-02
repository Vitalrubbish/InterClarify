"""Reject changed source/assets before any model import or GPU allocation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
from native_soulx_loader import CONFIG, verify_files, verify_source, load_native_controller


class LoaderTests(unittest.TestCase):
    def test_current_official_checkout_matches_every_frozen_source_file(self):
        config = json.loads(CONFIG.read_text())
        actual = verify_source(ROOT / 'third_party/soulx-duplug', config)
        self.assertEqual(len(actual), 21)
        self.assertEqual(config['runtime_config']['infer_config']['asr'],
                         {'model_name': 'sensevoice', 'language': 'en'})
        self.assertEqual(len(config['soulx_files']), 16)
        self.assertEqual(len(config['sensevoice_files']), 5)

    def test_wrong_commit_or_dirty_checkout_is_rejected(self):
        config = json.loads(CONFIG.read_text())
        for commit, dirty in (('wrong', ''), (config['source_commit'], ' M service/model.py')):
            with patch('native_soulx_loader.subprocess.check_output', side_effect=[commit, dirty]):
                with self.assertRaises(ValueError):
                    verify_source(ROOT / 'third_party/soulx-duplug', config)

    def test_asset_tamper_and_missing_file_are_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'weights.bin'
            path.write_bytes(b'frozen')
            frozen = {'weights.bin': hashlib.sha256(b'frozen').hexdigest()}
            self.assertEqual(verify_files(temporary, frozen), frozen)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                verify_files(temporary, frozen)
            with self.assertRaises(FileNotFoundError):
                verify_files(temporary, {'missing.bin': frozen['weights.bin']})

    def test_loader_never_attempts_model_load_without_valid_local_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch('native_soulx_loader.importlib.import_module') as import_module:
                with self.assertRaises(FileNotFoundError):
                    load_native_controller(ROOT / 'third_party/soulx-duplug', temporary, temporary, temporary)
                import_module.assert_not_called()


if __name__ == '__main__':
    unittest.main()
