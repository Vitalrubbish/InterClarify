"""CPU-only tests for the P1.1 offline control adapter (no model load)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from interclarify.duplex.official_control import (  # noqa: E402
    DEFAULT_SCRIPT,
    SPECIAL_TOKENS,
    append_user_micro_turn,
    build_prompt_tokens,
)

DEFAULT_MODEL_ROOT = "/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models"


def _find_tokenizer_dir() -> Path | None:
    explicit = os.environ.get("INTERCLARIFY_DUPLEXCASCADE_SNAPSHOT")
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    model_root = Path(os.environ.get("INTERCLARIFY_MODEL_ROOT", DEFAULT_MODEL_ROOT))
    base = model_root / "modelscope" / "sbintuitions--DuplexCascade"
    if base.is_dir():
        candidates.extend(sorted(p for p in base.iterdir() if p.is_dir()))
    for candidate in candidates:
        tokenizer_dir = candidate / "tokenizer"
        if tokenizer_dir.is_dir() and any(tokenizer_dir.iterdir()):
            return tokenizer_dir
    return None


@pytest.fixture(scope="module")
def tokenizer():
    tokenizer_dir = _find_tokenizer_dir()
    if tokenizer_dir is None:
        pytest.skip("DuplexCascade tokenizer snapshot not available")
    from transformers import AutoTokenizer

    try:
        tok = AutoTokenizer.from_pretrained(str(tokenizer_dir), use_fast=True, trust_remote_code=False)
    except Exception:
        tok = AutoTokenizer.from_pretrained(str(tokenizer_dir), use_fast=False, trust_remote_code=False)
    tok.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})
    return tok


def test_prompt_tokens_include_control_tokens(tokenizer) -> None:
    tokens = build_prompt_tokens(tokenizer)
    assert len(tokens.header_user) >= 1
    assert len(tokens.header_assist) >= 1
    assert len(tokens.no_voice_ids) == 1
    assert tokens.im_end_id is not None
    # five assistant control tokens, each a single added token id
    assert len(tokens.special_token_ids) == len(SPECIAL_TOKENS) - 1
    assert set(tokens.special_id_to_text.values()) == set(SPECIAL_TOKENS[1:])


def test_append_user_micro_turn_text_and_silence(tokenizer) -> None:
    tokens = build_prompt_tokens(tokenizer)

    history: list[int] = []
    append_user_micro_turn(tokens, history, "hello", tokenizer.encode)
    assert history[: len(tokens.header_user)] == tokens.header_user
    assert history[-len(tokens.header_assist):] == tokens.header_assist
    assert tokens.no_voice_ids[0] not in history

    silent: list[int] = []
    append_user_micro_turn(tokens, silent, None, tokenizer.encode)
    assert tokens.no_voice_ids[0] in silent


def test_default_script_shape() -> None:
    assert isinstance(DEFAULT_SCRIPT, tuple)
    assert len(DEFAULT_SCRIPT) >= 3
    assert any(item is None for item in DEFAULT_SCRIPT)
    assert any(isinstance(item, str) for item in DEFAULT_SCRIPT)
