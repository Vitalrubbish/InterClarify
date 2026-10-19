"""Validate interrupted-source recovery without contacting a dataset host."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / 'scripts/training/fetch_layer1_sources.py'
SPEC = importlib.util.spec_from_file_location('fetch_sources', PATH)
FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FETCH)


class Response:
    def __init__(self, status, blocks, content_range=None):
        self.status_code, self.blocks = status, blocks
        self.headers = {'Content-Range': content_range}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, size):
        for block in self.blocks:
            if isinstance(block, Exception):
                raise block
            yield block


class SourceRecoveryTests(unittest.TestCase):
    def test_disconnect_resumes_and_verifies_complete_content(self):
        payload = b'abcdefgh'
        checksum = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'shard.jsonl'
            responses = [Response(200, [b'abc', FETCH.requests.ConnectionError('disconnected')]),
                         Response(206, [b'defgh'], 'bytes 3-7/8')]
            with patch.object(FETCH.requests, 'get', side_effect=responses) as request:
                self.assertEqual(FETCH.fetch('https://example.test/data', path, 8, checksum, 2, 0), checksum)
                self.assertEqual(request.call_args_list[1].kwargs['headers'], {'Range': 'bytes=3-'})
            self.assertEqual(path.read_bytes(), payload)
            self.assertFalse(path.with_suffix('.jsonl.part').exists())

    def test_ignored_range_restarts_without_appending(self):
        payload = b'abcdefgh'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'shard.jsonl'
            path.with_suffix('.jsonl.part').write_bytes(b'abc')
            with patch.object(FETCH.requests, 'get', return_value=Response(200, [payload])):
                FETCH.fetch('https://example.test/data', path, 8, hashlib.sha256(payload).hexdigest(), 1, 0)
            self.assertEqual(path.read_bytes(), payload)

    def test_malformed_range_and_corrupt_payload_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'shard.jsonl'
            path.with_suffix('.jsonl.part').write_bytes(b'abc')
            with patch.object(FETCH.requests, 'get', return_value=Response(206, [b'defgh'], 'bytes 0-7/8')):
                with self.assertRaisesRegex(ValueError, 'range'):
                    FETCH.fetch('https://example.test/data', path, 8, 'wrong', 1, 0)
            with patch.object(FETCH.requests, 'get', return_value=Response(200, [b'abcdefgh'])):
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    FETCH.fetch('https://example.test/data', path, 8, 'wrong', 1, 0)
            self.assertFalse(path.exists())

    def test_retry_limit_retains_partial_and_existing_shard_is_reverified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'shard.jsonl'
            with patch.object(FETCH.requests, 'get', side_effect=FETCH.requests.Timeout('timeout')) as request:
                with self.assertRaises(FETCH.requests.Timeout):
                    FETCH.fetch('https://example.test/data', path, 8, 'wrong', 2, 0)
                self.assertEqual(request.call_count, 2)
            path.write_bytes(b'incorrect')
            with self.assertRaisesRegex(ValueError, 'Existing shard'):
                FETCH.fetch('https://example.test/data', path, 8, 'wrong', 1, 0)


if __name__ == '__main__':
    unittest.main()
