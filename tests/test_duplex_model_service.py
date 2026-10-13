"""Verify released checkpoint validation and cancellable HTTP wire contracts."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

SPEC = importlib.util.spec_from_file_location('duplex_service', Path(__file__).parents[1] / 'scripts/remote/duplex_model_service.py')
service = importlib.util.module_from_spec(SPEC)
# Pydantic resolves nested model annotations through sys.modules.
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


class FakeModel:
    """Return official markers without loading weights on the local machine."""

    info = {'token_ids': {'<|im_end|>': 151645}}

    async def stream(self, request):
        """Expose preserved text and model termination metadata."""
        yield {'text': '<|user is talking|>'}
        yield {'text': '<|im_end|>'}
        yield {'finish_reason': 'stop', 'token_ids': [151647, 151645], 'prompt_tokens': 7}


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
            body = {'history': [{'role': 'user', 'text': 'Hi'}]}
            response = client.post('/generate', json=body)
            self.assertEqual(response.status_code, 200)
            rows = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(''.join(x.get('text', '') for x in rows), '<|user is talking|><|im_end|>')
            self.assertEqual(rows[-1]['finish_reason'], 'stop')
            self.assertEqual(rows[-1]['token_ids'], [151647, 151645])
            self.assertEqual(client.post('/generate', json={'history': []}).status_code, 400)
            self.assertEqual(
                client.post('/generate', json={'history': [{'role': 'assistant', 'token_ids': [1]}]}).status_code,
                400,
            )
            self.assertEqual(client.post('/generate', json={'max_new_tokens': 0}).status_code, 422)

    def test_history_flattens_to_official_chatml_token_ids(self):
        """User text, silence markers and released ids reproduce the official run."""
        class Tokenizer:
            """Encode characters directly so expectations stay readable."""

            def encode(self, text, add_special_tokens=False):
                """Return one id per character."""
                return [ord(character) for character in text]

        model = object.__new__(service.OfficialDuplexModel)
        model.tokenizer = Tokenizer()
        model.header_user_ids = [1]
        model.header_assist_ids = [2]
        model.im_end_nl_ids = [3]
        model.no_voice_ids = [4]
        history = [
            service.HistoryTurn(role='user', text='Hi'),
            service.HistoryTurn(role='assistant', token_ids=[9, 3]),
            service.HistoryTurn(role='user', text='   '),
        ]
        self.assertEqual(
            model.build_prompt_ids(history),
            [1, ord('H'), ord('i'), 3, 2, 9, 3, 1, 4, 3, 2],
        )
        with self.assertRaises(ValueError):
            model.build_prompt_ids([])
        with self.assertRaises(ValueError):
            model.build_prompt_ids([service.HistoryTurn(role='assistant', token_ids=[1])])
        with self.assertRaises(ValueError):
            model.build_prompt_ids([
                service.HistoryTurn(role='user', text='x'),
                service.HistoryTurn(role='assistant', token_ids=[]),
                service.HistoryTurn(role='user', text='y'),
            ])

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
