"""Serve released DuplexCascade weights as cancellable raw ChatML completions."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import asyncio
import json
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Direct-script and test imports share the repository's normal training module.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from layer1_model import (
    WIRE_TOKENS, load_official_checkpoint, normalize_state_dict,
    validate_prompt_ids, validate_state_keys,
)


class PrefixCachePool:
    """Own bounded, exclusive session caches; all access holds the service lock.

    Parameters
    ----------
    max_sessions : int
        Maximum idle session caches.
    max_tokens : int
        Maximum tokens per retained cache.
    max_bytes : int
        Total retained tensor byte limit.
    ttl : float
        Idle expiry in seconds.
    """

    def __init__(self, max_sessions=2, max_tokens=8192, max_bytes=512 * 1024**2, ttl=300):
        self.entries = OrderedDict()
        self.max_sessions, self.max_tokens = max_sessions, max_tokens
        self.max_bytes, self.ttl = max_bytes, ttl

    def discard(self, session_id):
        """Remove one session, including during explicit release."""
        self.entries.pop(session_id, None)

    def take(self, session_id, ids):
        """Check out an exact prefix or rebuild after history revision."""
        now = time.monotonic()
        for key in list(self.entries):
            if now - self.entries[key]['at'] > self.ttl:
                self.discard(key)
        entry = self.entries.pop(session_id, None)
        if entry is None:
            return None, 0, 'cold'
        prefix = entry['ids']
        if len(prefix) < len(ids) and ids[:len(prefix)] == prefix:
            return entry['cache'], len(prefix), 'hit'
        return None, 0, 'prefix_invalidated'

    def store(self, session_id, cache, ids):
        """Retain only verified materialized tokens within all memory limits."""
        count = int(cache.get_seq_length())
        size = sum(t.numel() * t.element_size() for layer in cache for t in layer)
        if count <= 0 or count > len(ids):
            raise RuntimeError('Cache length does not match completed token history')
        if count > self.max_tokens or size > self.max_bytes:
            return False
        self.discard(session_id)
        self.entries[session_id] = dict(cache=cache, ids=list(ids[:count]), bytes=size,
                                       at=time.monotonic())
        while len(self.entries) > self.max_sessions or self.bytes_used() > self.max_bytes:
            self.entries.popitem(last=False)
        return session_id in self.entries

    def bytes_used(self):
        """Return retained tensor bytes, excluding the exclusively checked-out cache."""
        return sum(e['bytes'] for e in self.entries.values())


class HistoryTurn(BaseModel):
    """One prior micro-turn: user text or the assistant's generated token ids."""

    role: str
    text: str = ''
    token_ids: list[int] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    """One official micro-turn history and its system micro-turn budget."""

    session_id: str = Field(default='', max_length=128, pattern=r'^[A-Za-z0-9_-]*$')
    request_id: str = Field(default='', max_length=128)
    use_cache: bool = False
    history: list[HistoryTurn] = Field(default_factory=list)
    max_new_tokens: int = Field(default=64, ge=1, le=256)
    audit_prompt: bool = False


class GenerateIDsRequest(BaseModel):
    """Accept independent reference prompt IDs for offline runtime diagnostics."""

    session_id: str = Field(default='', max_length=128, pattern=r'^[A-Za-z0-9_-]*$')
    request_id: str = Field(default='', max_length=128)
    use_cache: bool = False
    prompt_token_ids: list[int] = Field(min_length=1)
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

    def __init__(self, checkpoint: Path, base_model: Path, device: str = 'cuda',
                 adaptation: Path | None = None) -> None:
        import resource
        started = time.monotonic()
        def phase(name):
            print(json.dumps({'duplex_load': {'phase': name,
                'seconds': time.monotonic()-started,
                'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}), flush=True)
        loaded = load_official_checkpoint(checkpoint, base_model, device, training=False, phase=phase)
        if adaptation is not None:
            from layer1_candidate import load_candidate
            loaded.info['adaptation'] = load_candidate(loaded, adaptation, checkpoint, base_model)
        else:
            loaded.info['adaptation'] = {'condition': 'B0', 'updated': False}
        self.tokenizer = loaded.tokenizer
        self.token_ids = loaded.token_ids
        self.model = loaded.model
        self.device = device
        self.header_user_ids = self.tokenizer.encode('<|im_start|>user\n', add_special_tokens=False)
        self.header_assist_ids = self.tokenizer.encode('<|im_start|>assistant\n', add_special_tokens=False)
        self.im_end_nl_ids = self.tokenizer.encode('<|im_end|>\n', add_special_tokens=False)
        self.no_voice_ids = self.tokenizer.encode('<|no voice|>', add_special_tokens=False)
        self.bos_id = self.tokenizer.bos_token_id
        self.eos_id = self.token_ids['<|im_end|>']
        self.context_length = loaded.info['context_length']
        self.info = loaded.info
        self.cache_pool = PrefixCachePool()
        self.trace_path = None

    def build_prompt_ids(self, history: list[HistoryTurn]) -> list[int]:
        """Flatten one micro-turn history into the official raw ChatML id run.

        Parameters
        ----------
        history : list[HistoryTurn]
            Alternating user micro-turns and assistant generated ids. The final
            turn must be the user micro-turn that triggered this inference.

        Returns
        -------
        list[int]
            Header, content and end-of-message ids ending with the assistant
            header, exactly as the released server concatenates them.
        """
        if not history or history[-1].role != 'user':
            raise ValueError('history must end with a user micro-turn')
        ids: list[int] = [] if self.bos_id is None else [int(self.bos_id)]
        for turn in history:
            if turn.role not in ('user', 'assistant'):
                raise ValueError(f'unknown history role: {turn.role!r}')
            if turn.role == 'user':
                ids.extend(self.header_user_ids)
                text = turn.text.strip()
                if text:
                    ids.extend(self.tokenizer.encode(text, add_special_tokens=False))
                else:
                    ids.extend(self.no_voice_ids)
                ids.extend(self.im_end_nl_ids)
            else:
                if not turn.token_ids:
                    raise ValueError('assistant micro-turns require generated token ids')
                ids.extend(self.header_assist_ids)
                ids.extend(int(token_id) for token_id in turn.token_ids)
        ids.extend(self.header_assist_ids)
        return ids

    async def stream(self, request: GenerateRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded text and completion reason, cancelling disconnected clients.

        Parameters
        ----------
        request : GenerateRequest
            Raw micro-turn history and generation limit.
        """
        ids = self.build_prompt_ids(request.history)
        async for item in self.stream_ids(ids, request.max_new_tokens, request.audit_prompt,
                                          session_id=request.session_id, request_id=request.request_id,
                                          use_cache=request.use_cache):
            yield item

    async def stream_ids(self, ids: list[int], max_new_tokens: int, audit_prompt: bool = True, *, session_id: str = "",
                         request_id: str = "", use_cache: bool = False) -> AsyncIterator[dict[str, Any]]:
        """Run the same inference kernel on independently constructed reference IDs.

        Parameters
        ----------
        ids : list[int]
            Raw diagnostic prompt IDs, bypassing history construction.
        max_new_tokens : int
            Frozen generation budget.
        audit_prompt : bool
            Whether to emit the exact consumed prompt.
        """
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        from transformers.generation.streamers import BaseStreamer

        validation_started = time.monotonic()
        validate_prompt_ids(ids, self.tokenizer)
        validation_seconds = time.monotonic() - validation_started
        if len(ids) + max_new_tokens > self.context_length:
            raise ValueError(f'Raw micro-turn history exceeds model context length: '
                             f'{len(ids)} prompt tokens + {max_new_tokens} new tokens '
                             f'> {self.context_length}')
        if use_cache and not session_id:
            raise ValueError('Caching requires an explicit session_id')
        cached, prefix_length, cache_status = (self.cache_pool.take(session_id, ids)
            if use_cache else (None, 0, 'disabled'))
        if use_cache and cached is None:
            from transformers import DynamicCache
            cached = DynamicCache()
        # Transformers 4.46 derives cache_position from the full input length,
        # then prepare_inputs_for_generation slices the unprocessed suffix.
        tensor = torch.tensor([ids], dtype=torch.long, device=self.device)
        request_started = time.monotonic()
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
                self.first_token_at = None

            def put(self, value):
                """Skip prompt tokens and expose generated markers verbatim."""
                if self.prompt:
                    self.prompt = False
                    return
                if self.first_token_at is None:
                    self.first_token_at = time.monotonic()
                self.ids.extend(int(value) for value in value.reshape(-1).tolist())
                for token_id in value.reshape(-1).tolist():
                    items.put({'generated_token_id': int(token_id)})
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
            """Run one official greedy generation outside the HTTP event loop.

            ``num_logits_to_keep=1`` keeps only the final position's LM head
            output. The official server materializes logits for every prompt
            position and slices the last one; both produce identical ids, while
            the flag avoids the multi-gigabyte allocation that OOMed long
            histories.
            """
            started = time.monotonic()
            try:
                with torch.inference_mode():
                    self.model.generate(input_ids=tensor,
                        attention_mask=torch.ones((1, len(ids)), dtype=torch.long, device=self.device),
                        max_new_tokens=max_new_tokens, eos_token_id=eos_id,
                        pad_token_id=eos_id, do_sample=False, streamer=streamer,
                        num_logits_to_keep=1, use_cache=True,
                        **({"past_key_values": cached}
                           if use_cache else {}),
                        stopping_criteria=StoppingCriteriaList([Cancellation()]))
                reason = 'stop' if streamer.ids and streamer.ids[-1] == eos_id else 'length'
                peak = torch.cuda.max_memory_allocated() / 2 ** 30 if self.device.startswith('cuda') else 0.0
                completed = time.monotonic()
                retained = False
                if use_cache and not stop.is_set():
                    retained = self.cache_pool.store(session_id, cached, ids + streamer.ids)
                metrics = {
                    'session_id': session_id, 'request_id': request_id,
                    'prompt_tokens': len(ids), 'generated_tokens': len(streamer.ids),
                    'cached_tokens': prefix_length, 'new_input_tokens': len(ids) - prefix_length,
                    'cache_status': cache_status, 'cache_retained': retained,
                    'cache_bytes': self.cache_pool.bytes_used(),
                    'request_started_monotonic': request_started,
                    'model_started_monotonic': started, 'model_finished_monotonic': completed,
                    'first_token_monotonic': streamer.first_token_at,
                    'request_to_first_token_seconds': (streamer.first_token_at - request_started
                                                      if streamer.first_token_at else None),
                    'model_to_first_token_seconds': (streamer.first_token_at - started
                                                    if streamer.first_token_at else None),
                    'validation_seconds': validation_seconds, 'finish_reason': reason,
                    'seconds': completed - started, 'peak_gpu_gib': peak,
                }
                print(json.dumps({'duplex_request': metrics}), flush=True)
                if self.trace_path is not None:
                    with self.trace_path.open('a') as trace:
                        trace.write(json.dumps({**metrics, 'prompt_token_ids': ids,
                                               'token_ids': streamer.ids}) + '\n')
                completion = {'finish_reason': reason, 'token_ids': list(streamer.ids),
                              'prompt_tokens': len(ids), 'metrics': metrics}
                if audit_prompt:
                    completion['prompt_token_ids'] = ids
                items.put(completion)
            except Exception as exc:
                items.put({'error': str(exc)})
            finally:
                items.put({'done': True})

        if audit_prompt:
            yield {'prompt_audit': True, 'prompt_token_ids': ids}

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()
        consumed = False
        try:
            while True:
                try:
                    item = items.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                if item.get('done'):
                    consumed = True
                    break
                yield item
        finally:
            stop.set()
            await asyncio.to_thread(thread.join)
            if use_cache and not consumed:
                self.cache_pool.discard(session_id)


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
        if not request.history or request.history[-1].role != 'user':
            raise HTTPException(400, 'Expected history ending with a user micro-turn')

        async def rows():
            """Hold the shared model lock until generation or cancellation ends."""
            async with lock:
                try:
                    async for item in model.stream(request):
                        yield json.dumps(item, ensure_ascii=False) + '\n'
                except (ValueError, RuntimeError) as exc:
                    yield json.dumps({'error': str(exc)}, ensure_ascii=False) + '\n'

        return StreamingResponse(rows(), media_type='application/x-ndjson')

    @app.delete('/cache/{session_id}')
    async def release_cache(session_id: str):
        """Release one idle session under the generation lock."""
        async with lock:
            model.cache_pool.discard(session_id)
        return {'released': session_id}

    @app.post('/generate_ids')
    async def generate_ids(request: GenerateIDsRequest):
        """Execute reference IDs without using the integration history renderer."""
        async def rows():
            async with lock:
                try:
                    async for item in model.stream_ids(request.prompt_token_ids, request.max_new_tokens,
                            session_id=request.session_id, request_id=request.request_id,
                            use_cache=request.use_cache):
                        yield json.dumps(item, ensure_ascii=False) + '\n'
                except (ValueError, RuntimeError) as exc:
                    yield json.dumps({'error': str(exc)}) + '\n'
        return StreamingResponse(rows(), media_type='application/x-ndjson')

    return app


def main() -> None:
    """Start the official-weight service inside the remote conda environment."""
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--base-model', type=Path, required=True)
    parser.add_argument('--adaptation', type=Path)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8006)
    parser.add_argument('--trace-path', type=Path)
    args = parser.parse_args()
    model = OfficialDuplexModel(args.checkpoint, args.base_model, args.device, args.adaptation)
    model.trace_path = args.trace_path
    uvicorn.run(create_app(model), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
