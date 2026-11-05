"""Reject changed source/assets before any model import or GPU allocation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
from native_soulx_loader import CONFIG, verify_files, verify_source, load_native_controller


class LoaderTests(unittest.TestCase):
    def test_loading_passes_explicit_ncpu_and_records_actual_budget(self):
        state = {'cpu': 4}
        calls = []
        tokens = {'<|user_complete|>': 151676, '<|user_backchannel|>': 151677,
                  '<|user_incomplete|>': 151678, '<|user_idle|>': 151680, '<|user_nonidle|>': 151681}

        def auto_model(**kwargs):
            calls.append(kwargs)
            state['cpu'] = kwargs.get('ncpu', 4)
            return SimpleNamespace(kwargs=kwargs)

        funasr = SimpleNamespace(AutoModel=auto_model)
        torch = SimpleNamespace(set_num_threads=lambda n: state.update(cpu=n),
            get_num_threads=lambda: state['cpu'], get_num_interop_threads=lambda: 1,
            cuda=SimpleNamespace(synchronize=lambda: None))

        def turn_model(**kwargs):
            teacher = funasr.AutoModel(model='iic/SenseVoiceSmall', device='cuda')
            tokenizer = SimpleNamespace(encode=lambda t, **kw: [tokens[t]],
                decode=lambda i, **kw: next(t for t, v in tokens.items() if v == i[0]))
            return SimpleNamespace(cascade_asr=SimpleNamespace(sensevoice_model=teacher),
                                   model=SimpleNamespace(tokenizer=tokenizer))

        with tempfile.TemporaryDirectory() as directory, \
                patch('native_soulx_loader.verify_source', return_value={}), \
                patch('native_soulx_loader.verify_files', return_value={}), \
                patch.dict(sys.modules, {'torch': torch, 'funasr': funasr}), \
                patch('native_soulx_loader.importlib.import_module', return_value=SimpleNamespace(TurnModel=turn_model)), \
                patch('native_soulx_loader.NativeSoulX', return_value=SimpleNamespace()):
            value = load_native_controller(directory, directory, directory, directory)
            observed = json.loads((Path(directory)/'execution.json').read_text())
        self.assertEqual(calls[0]['ncpu'], 2)
        self.assertEqual(observed['cpu_threads'], 2)
        self.assertEqual(observed['sensevoice_ncpu'], 2)
        self.assertEqual(value.execution_manifest, observed)

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
