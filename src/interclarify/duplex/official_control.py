"""Thin offline adapter around the official DuplexCascade control model.

The official repository only ships a real-time ``server.py`` entry point.  For
P1.1 we inject a fixed text input and run the same micro-turn generation loop,
while keeping the official weights and control tokens untouched.

What is reused verbatim from the official code
----------------------------------------------
- ``3rd-party/DuplexCascade/model.py`` (``Model`` + LoRA adapter) is imported
  from disk, not modified;
- the six conversational control tokens and the ChatML prompt assembly mirror
  ``server.py`` (``SPECIAL_TOKENS`` / ``prepare_llm_tokens`` / the per-tick
  prompt in ``llm_tick_task``);
- the DuplexCascade ``model_state.safetensors`` is loaded with ``strict=False``
  exactly like ``server.py``.

What this module adds
---------------------
- a synchronous, single-process driver that feeds a scripted list of micro-turn
  texts (or silence) instead of a live ASR stream;
- raw-output capture plus per-turn latency so the caller can compute retry-free
  measurements such as GPU peak memory and a real-time factor relative to the
  0.6 s micro-turn window.

It deliberately does **not** add any InterClarify Layer 2 decision logic.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence

# Conversational control tokens, in the official order (server.py SPECIAL_TOKENS).
SPECIAL_TOKENS = [
    "<|no voice|>",
    "<|user is talking|>",
    "<|user finish talking|>",
    "<|user is thinking|>",
    "<|user interruption|>",
    "<|user backchannel|>",
]

# Assistant-side control tokens (excludes <|no voice|>, which is a user marker).
_ASSISTANT_SPECIALS = SPECIAL_TOKENS[1:]

# Official default overlap window, used as the micro-turn reference for RTF.
DEFAULT_MICRO_TURN_SECONDS = 0.6

# Minimal neutral script used when no ``--script`` is given.  The official
# README ships no example utterance, so we use a short greeting exchange that
# exercises "user talking" -> "user finished" -> a silent micro-turn -> a
# short reply request, without domain-specific content.
DEFAULT_SCRIPT: tuple[Optional[str], ...] = (
    "Hello",
    "how are you today",
    None,  # micro-turn with no new user words (official <|no voice|>)
    "could you tell me a short joke",
)


@dataclass
class PromptTokens:
    """Token-id lookup tables mirroring server.py ``prepare_llm_tokens``."""

    bos_id: Optional[int]
    header_user: List[int]
    header_assist: List[int]
    im_end_ids: List[int]
    im_end_id: int
    im_end_nl_ids: List[int]
    nl_ids: List[int]
    no_voice_ids: List[int]
    special_token_ids: set[int]
    special_id_to_text: dict[int, str]
    skip_for_text: set[int]


@dataclass
class MicroTurnResult:
    index: int
    user_text: Optional[str]
    prompt_tokens: int
    generated_token_ids: List[int]
    assistant_special: List[str]
    assistant_text: str
    latency_s: float


def build_prompt_tokens(tokenizer: Any) -> PromptTokens:
    """Build the token lookup tables used by the official server."""

    def get_ids(text: str) -> List[int]:
        return tokenizer.encode(text, add_special_tokens=False)

    bos_id = tokenizer.bos_token_id
    header_user = get_ids("<|im_start|>user\n")
    header_assist = get_ids("<|im_start|>assistant\n")
    im_end_ids = get_ids("<|im_end|>")
    im_end_id = im_end_ids[0] if im_end_ids else tokenizer.eos_token_id
    im_end_nl_ids = get_ids("<|im_end|>\n") or list(im_end_ids)
    nl_ids = get_ids("\n")
    no_voice_ids = get_ids("<|no voice|>")

    special_token_ids: set[int] = set()
    special_id_to_text: dict[int, str] = {}
    for text in _ASSISTANT_SPECIALS:
        for tid in get_ids(text):
            special_token_ids.add(int(tid))
            special_id_to_text[int(tid)] = text

    skip_for_text: set[int] = set(special_token_ids)
    skip_for_text.update(int(t) for t in no_voice_ids)
    for tid in header_user + header_assist + list(im_end_nl_ids) + list(im_end_ids) + list(nl_ids):
        skip_for_text.add(int(tid))

    return PromptTokens(
        bos_id=bos_id,
        header_user=header_user,
        header_assist=header_assist,
        im_end_ids=im_end_ids,
        im_end_id=im_end_id,
        im_end_nl_ids=im_end_nl_ids,
        nl_ids=nl_ids,
        no_voice_ids=no_voice_ids,
        special_token_ids=special_token_ids,
        special_id_to_text=special_id_to_text,
        skip_for_text=skip_for_text,
    )


def append_user_micro_turn(
    tokens: PromptTokens,
    history_ids: List[int],
    delta_text: Optional[str],
    encode,
) -> None:
    """Append one official micro-turn user segment to ``history_ids`` in place.

    Mirrors the per-tick prompt construction in server.py ``llm_tick_task``:
    a user header, either the new words or ``<|no voice|>``, ``<|im_end|>\\n``
    and then the assistant header.
    """
    history_ids.extend(tokens.header_user)
    if delta_text and delta_text.strip():
        history_ids.extend(encode(delta_text))
    else:
        history_ids.extend(tokens.no_voice_ids)
    history_ids.extend(tokens.im_end_nl_ids)
    history_ids.extend(tokens.header_assist)


def _load_official_model_class(source_root: Path) -> Any:
    """Import the official ``model.py`` ``Model`` class without modifying it."""
    model_file = source_root / "model.py"
    if not model_file.is_file():
        raise FileNotFoundError(f"official DuplexCascade model.py not found: {model_file}")
    spec = importlib.util.spec_from_file_location("interclarify_official_duplexcascade_model", model_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import official model from {model_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Model


class OfficialControlAdapter:
    """Load the fixed DuplexCascade control model and run scripted micro-turns."""

    def __init__(
        self,
        *,
        snapshot_dir: Path | str,
        base_model_path: Path | str,
        source_root: Path | str,
        device: str = "cuda",
        dtype: str = "bfloat16",
        max_new_tokens: int = 64,
        micro_turn_seconds: float = DEFAULT_MICRO_TURN_SECONDS,
    ) -> None:
        import torch
        from transformers import AutoTokenizer

        self.snapshot_dir = Path(snapshot_dir)
        self.base_model_path = Path(base_model_path)
        self.source_root = Path(source_root)
        self.device = device
        self.max_new_tokens = int(max_new_tokens)
        self.micro_turn_seconds = float(micro_turn_seconds)

        torch_dtype = getattr(torch, dtype)
        self._torch = torch

        tokenizer_dir = self.snapshot_dir / "tokenizer"
        tokenizer_source = str(tokenizer_dir) if tokenizer_dir.is_dir() and any(tokenizer_dir.iterdir()) else str(self.base_model_path)
        # The pinned transformers/tokenizers cannot parse this repo's fast
        # tokenizer.json ("untagged enum ModelWrapper"); fall back to the slow
        # Qwen2 tokenizer, which yields equivalent token ids.
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, use_fast=True, trust_remote_code=False)
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, use_fast=False, trust_remote_code=False)
        self.tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})

        Model = _load_official_model_class(self.source_root)
        self.model = Model(
            tokenizer=self.tokenizer,
            model_name=str(self.base_model_path),
            trust_remote_code=False,
            torch_dtype=torch_dtype,
            attn_implementation="sdpa",
        )
        self.model.enable_lora_adapter()
        self.model.to(self.device)
        self.model.eval()

        from safetensors.torch import load_file

        weight_path = self.snapshot_dir / "model_state.safetensors"
        state_dict = load_file(str(weight_path), device="cpu")
        self.model.load_state_dict(state_dict, strict=False)
        del state_dict

        self.tokens = build_prompt_tokens(self.tokenizer)

    def _encode(self, text: str) -> List[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def cuda_peak_memory_mb(self) -> dict[str, Optional[float]]:
        """Return peak CUDA memory in MiB (allocated/reserved), or None on CPU."""
        torch = self._torch
        if torch.cuda.is_available() and str(self.device).startswith("cuda"):
            return {
                "allocated": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
                "reserved": round(torch.cuda.max_memory_reserved() / 1024**2, 2),
            }
        return {"allocated": None, "reserved": None}

    def run_turn(self, history_ids: List[int], delta_text: Optional[str], index: int = 0) -> MicroTurnResult:
        torch = self._torch

        # Build the input the same way the official server does per micro-turn.
        append_user_micro_turn(self.tokens, history_ids, delta_text, self._encode)
        input_ids = torch.tensor([history_ids], dtype=torch.long, device=self.device)
        attention_mask = torch.ones_like(input_ids)

        if torch.cuda.is_available() and self.device.startswith("cuda"):
            torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.no_grad():
            output = self.model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=self.tokens.im_end_id,
                pad_token_id=self.tokens.im_end_id,
                do_sample=False,
            )
        if torch.cuda.is_available() and self.device.startswith("cuda"):
            torch.cuda.synchronize()
        latency = time.perf_counter() - start

        prompt_len = input_ids.shape[1]
        generated = [int(t) for t in output[0, prompt_len:].tolist()]

        specials, text = self._parse_generated(history_ids, generated)

        return MicroTurnResult(
            index=index,
            user_text=delta_text,
            prompt_tokens=prompt_len,
            generated_token_ids=generated,
            assistant_special=specials,
            assistant_text=text,
            latency_s=latency,
        )

    def _parse_generated(self, history_ids: List[int], generated: Sequence[int]) -> tuple[List[str], str]:
        """Split generated tokens into specials and text, mirroring server.py."""
        specials: List[str] = []
        pending: List[int] = []
        text = ""
        for tid in generated:
            history_ids.append(int(tid))
            if tid in self.tokens.special_token_ids:
                text += self._flush(pending)
                pending = []
                specials.append(self.tokens.special_id_to_text.get(int(tid), str(tid)))
            elif tid in self.tokens.skip_for_text:
                if tid in self.tokens.im_end_ids or tid in self.tokens.im_end_nl_ids:
                    text += self._flush(pending)
                    pending = []
            else:
                pending.append(int(tid))
        text += self._flush(pending)
        return specials, text

    def _flush(self, pending: List[int]) -> str:
        if not pending:
            return ""
        # Decode the pending buffer; official server does the same full decode.
        return self.tokenizer.decode(pending, skip_special_tokens=True)

    def run_script(self, script: Sequence[Optional[str]]) -> List[MicroTurnResult]:
        history_ids: List[int] = []
        if self.tokens.bos_id is not None:
            history_ids.append(int(self.tokens.bos_id))
        results: List[MicroTurnResult] = []
        for index, delta_text in enumerate(script, 1):
            result = self.run_turn(history_ids, delta_text, index=index)
            results.append(result)
        return results
