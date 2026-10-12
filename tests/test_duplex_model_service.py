"""Verify released checkpoint validation and cancellable HTTP wire contracts."""

import importlib.util
import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

SPEC = importlib.util.spec_from_file_location('duplex_service', Path(__file__).parents[1] / 'scripts/remote/duplex_model_service.py')
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class FakeModel:
    """Return official markers without loading weights on the local machine."""

    info = {'token_ids': {'<|im_end|>': 151645}}

    async def stream(self, request):
        """Expose preserved text and model termination metadata."""
        yield {'text': '<|user is talking|>'}
        yield {'text': '<|im_end|>'}
        yield {'finish_reason': 'stop'}


class DuplexModelServiceTests(unittest.TestCase):
    """Test the service boundary without GPU or checkpoint downloads."""

    def test_checkpoint_validation(self):
        """Missing or extra keys cannot silently initialize an invalid model."""
        service.validate_state_keys({'a', 'b'}, {'a', 'b'})
        for supplied in ({'a'}, {'a', 'b', 'c'}):
            with self.assertRaises(ValueError):
                service.validate_state_keys({'a', 'b'}, supplied)

    def test_health_and_raw_chatml_stream(self):
        """HTTP preserves actual special markers and an explicit stop reason."""
        with TestClient(service.create_app(FakeModel())) as client:
            self.assertEqual(client.get('/health').json()['token_ids']['<|im_end|>'], 151645)
            response = client.post('/generate', json={'prompt': '<|im_start|>user\nHi<|im_end|>\n<|im_start|>assistant\n'})
            self.assertEqual(response.status_code, 200)
            rows = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(''.join(x.get('text', '') for x in rows), '<|user is talking|><|im_end|>')
            self.assertEqual(rows[-1]['finish_reason'], 'stop')
            self.assertEqual(client.post('/generate', json={'prompt': 'ordinary chat'}).status_code, 400)
            self.assertEqual(client.post('/generate', json={'prompt': '', 'max_new_tokens': 0}).status_code, 422)

    def test_published_qv_base_weights_are_mapped_without_ignoring_tensors(self):
        """Legacy released base weights load into PEFT base_layer with no value changes."""
        weight = object()
        original = 'llm.base_model.model.model.layers.0.self_attn.q_proj.weight'
        target = original.replace('q_proj.weight', 'q_proj.base_layer.weight')
        mapped = service.normalize_state_dict({original: weight}, {target})
        self.assertIs(mapped[target], weight)
        with self.assertRaises(ValueError):
            service.normalize_state_dict({original: weight, target: weight}, {target})
        with self.assertRaises(ValueError):
            service.normalize_state_dict({'unknown': weight}, {target})
