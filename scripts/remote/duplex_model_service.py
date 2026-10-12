"""Serve released DuplexCascade weights as cancellable raw ChatML completions."""

from __future__ import annotations

import argparse
import asyncio
import json
import queue
import re
import threading
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

WIRE_TOKENS = (
    '<|no voice|>', '<|user is talking|>', '<|user finish talking|>',
    '<|user is thinking|>', '<|user interruption|>', '<|user backchannel|>',
)


def validate_state_keys(expected: set[str], supplied: set[str]) -> None:
    """Reject incomplete checkpoints instead of serving partially initialized weights.

    Parameters
    ----------
    expected, supplied : set[str]
        Model and released state-dictionary key sets.
    """
    missing, extra = expected - supplied, supplied - expected
    if missing or extra:
        raise ValueError(f'Checkpoint keys mismatch: missing={sorted(missing)[:8]}, extra={sorted(extra)[:8]}')


def normalize_state_dict(state: dict[str, Any], expected: set[str]) -> dict[str, Any]:
    """Map published q/v base-weight names to current PEFT wrappers without changing tensors.

    Parameters
    ----------
    state : dict[str, Any]
        Published state dictionary.
    expected : set[str]
        Instantiated model keys.

    Returns
    -------
    dict[str, Any]
        The same tensors under validated, unique model keys.
    """
    normalized = {}
    for key, tensor in state.items():
        target = key
        if key not in expected:
            candidate = re.sub(r"\.(q_proj|v_proj)\.(weight|bias)$", r".\1.base_layer.\2", key)
            if candidate in expected:
                target = candidate
        if target in normalized:
            raise ValueError(f'Checkpoint mapping collision: {target}')
        normalized[target] = tensor
    validate_state_keys(expected, set(normalized))
    return normalized


class GenerateRequest(BaseModel):
    """One complete official ChatML prompt and its system micro-turn budget."""

    prompt: str
    max_new_tokens: int = Field(default=64, ge=1, le=256)


class OfficialDuplexModel:
    """Load the official Qwen2/LoRA inference wrapper from local model assets.

    Parameters
    ----------
    checkpoint : Path
        Published tokenizer, train_cfg.json and model_state.safetensors directory.
    base_model : Path
        Local Qwen2-7B-Instruct snapshot.
    device : str
        Allocated CUDA device or explicit CPU for inspection.
    """

    def __init__(self, checkpoint: Path, base_model: Path, device: str = 'cuda') -> None:
        import torch
        from peft import LoraConfig, TaskType, get_peft_model
        from safetensors.torch import load_file
        from transformers import AutoModelForCausalLM, AutoTokenizer

        cfg = json.loads((checkpoint / 'train_cfg.json').read_text())['model']
        if cfg.get('use_lora') != 'qv' or cfg.get('name') != 'Qwen/Qwen2-7B-Instruct':
            raise ValueError('Expected official Qwen2-7B-Instruct q/v LoRA checkpoint')
        self.tokenizer = AutoTokenizer.from_pretrained(str(checkpoint / 'tokenizer'), use_fast=False, local_files_only=True)
        self.token_ids = {}
        for marker in (*WIRE_TOKENS, '<|im_end|>'):
            ids = self.tokenizer.encode(marker, add_special_tokens=False)
            if len(ids) != 1 or self.tokenizer.convert_ids_to_tokens(ids[0]) != marker:
                raise ValueError(f'Expected one registered special token for {marker}')
            self.token_ids[marker] = ids[0]
        # Official releases rely on this registration order and embedding shape.
        self.tokenizer.add_special_tokens({'additional_special_tokens': list(WIRE_TOKENS)})
        base = AutoModelForCausalLM.from_pretrained(str(base_model), local_files_only=True,
            torch_dtype=torch.bfloat16 if device.startswith('cuda') else torch.float32,
            trust_remote_code=bool(cfg.get('trust_remote_code', False)))
        base.resize_token_embeddings(len(self.tokenizer))
        adapted = get_peft_model(base, LoraConfig(
            r=int(cfg.get('lora_r', 16)), lora_alpha=int(cfg.get('lora_alpha', 32)),
            lora_dropout=float(cfg.get('lora_dropout', 0.05)), bias=cfg.get('lora_bias', 'none'),
            task_type=TaskType.CAUSAL_LM, target_modules=['q_proj', 'v_proj'],
            modules_to_save=['embed_tokens', 'lm_head']))
        # The official Model wrapper nests the PEFT model under llm.
        wrapper = torch.nn.Module()
        wrapper.add_module('llm', adapted)
        state = load_file(str(checkpoint / 'model_state.safetensors'), device='cpu')
        state = normalize_state_dict(state, set(wrapper.state_dict()))
        wrapper.load_state_dict(state, strict=True)
        del state
        self.model = adapted.to(device).eval()
        self.model.requires_grad_(False)
        self.device = device
        self.eos_id = self.token_ids['<|im_end|>']
        self.context_length = int(base.config.max_position_embeddings)
        self.info = {'checkpoint': str(checkpoint.resolve()), 'base_model': str(base_model.resolve()),
                     'token_ids': self.token_ids, 'context_length': self.context_length,
                     'torch': torch.__version__, 'tokenizer_class': type(self.tokenizer).__name__,
                     'dtype': str(next(self.model.parameters()).dtype)}

    async def stream(self, request: GenerateRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded text and completion reason, cancelling disconnected clients.

        Parameters
        ----------
        request : GenerateRequest
            Raw ChatML prompt and generation limit.
        """
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        from transformers.generation.streamers import BaseStreamer

        ids = self.tokenizer.encode(request.prompt, add_special_tokens=False)
        if len(ids) + request.max_new_tokens > self.context_length:
            raise ValueError('Raw micro-turn history exceeds model context length')
        tensor = torch.tensor([ids], dtype=torch.long, device=self.device)
        items: queue.Queue[dict[str, Any]] = queue.Queue()
        stop = threading.Event()
        tokenizer = self.tokenizer
        eos_id = self.eos_id

        class Cancellation(StoppingCriteria):
            """Interrupt GPU decoding after client cancellation."""

            def __call__(self, input_ids, scores, **kwargs):
                return stop.is_set()

        class TokenStreamer(BaseStreamer):
            """Decode cumulative generated tokens without losing split Unicode."""

            def __init__(self):
                self.prompt = True
                self.ids = []
                self.previous = ''

            def put(self, value):
                """Skip prompt tokens and expose generated markers verbatim."""
                if self.prompt:
                    self.prompt = False
                    return
                self.ids.extend(int(value) for value in value.reshape(-1).tolist())
                self._emit(final=False)

            def _emit(self, final):
                """Hold incomplete UTF-8 decoding until its next token arrives."""
                decoded = tokenizer.decode(self.ids, skip_special_tokens=False,
                                           clean_up_tokenization_spaces=False)
                if not final and decoded.endswith('\ufffd'):
                    return
                if not decoded.startswith(self.previous):
                    raise RuntimeError('Tokenizer output revised an already emitted prefix')
                suffix = decoded[len(self.previous):]
                if suffix:
                    items.put({'text': suffix})
                self.previous = decoded

            def end(self):
                """Flush a complete final Unicode prefix."""
                self._emit(final=True)

        streamer = TokenStreamer()

        def generate():
            """Run one official greedy generation outside the HTTP event loop."""
            try:
                with torch.inference_mode():
                    self.model.generate(input_ids=tensor, attention_mask=torch.ones_like(tensor),
                        max_new_tokens=request.max_new_tokens, eos_token_id=eos_id,
                        pad_token_id=eos_id, do_sample=False, streamer=streamer,
                        stopping_criteria=StoppingCriteriaList([Cancellation()]))
                reason = 'stop' if streamer.ids and streamer.ids[-1] == eos_id else 'length'
                items.put({'finish_reason': reason})
            except Exception as exc:
                items.put({'error': str(exc)})
            finally:
                items.put({'done': True})

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()
        try:
            while True:
                try:
                    item = items.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                if item.get('done'):
                    break
                yield item
        finally:
            stop.set()
            await asyncio.to_thread(thread.join)


def create_app(model: OfficialDuplexModel) -> FastAPI:
    """Expose health and one serialized NDJSON raw-prompt endpoint.

    Parameters
    ----------
    model : OfficialDuplexModel
        Loaded released model; test callers may inject an equivalent fake.
    """
    app = FastAPI(title='DuplexCascade official weights')
    lock = asyncio.Lock()

    @app.get('/health')
    async def health():
        """Return model provenance and actual special token IDs."""
        return {'status': 'ok', **model.info}

    @app.post('/generate')
    async def generate(request: GenerateRequest):
        """Stream token-preserving NDJSON with explicit finish reasons."""
        if not request.prompt.endswith('<|im_start|>assistant\n'):
            raise HTTPException(400, 'Expected raw ChatML assistant header')

        async def rows():
            """Hold the shared model lock until generation or cancellation ends."""
            async with lock:
                try:
                    async for item in model.stream(request):
                        yield json.dumps(item, ensure_ascii=False) + '\n'
                except (ValueError, RuntimeError) as exc:
                    yield json.dumps({'error': str(exc)}, ensure_ascii=False) + '\n'

        return StreamingResponse(rows(), media_type='application/x-ndjson')

    return app


def main() -> None:
    """Start the official-weight service inside the remote conda environment."""
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--base-model', type=Path, required=True)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8006)
    args = parser.parse_args()
    model = OfficialDuplexModel(args.checkpoint, args.base_model, args.device)
    uvicorn.run(create_app(model), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
