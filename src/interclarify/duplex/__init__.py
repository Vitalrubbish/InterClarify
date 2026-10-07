"""DuplexCascade reproduction layer (P1).

This package adapts the *official, unmodified* DuplexCascade inference code
(vendored under ``3rd-party/DuplexCascade``) for offline use.  It does not
reimplement the control model: it loads the official ``model.py`` and mirrors
the prompt/control-token handling of the official ``server.py`` so that a
fixed text input can drive the same micro-turn generation loop without the
real-time ASR/TTS services (those belong to P1.2).
"""

from .official_control import (
    DEFAULT_SCRIPT,
    PromptTokens,
    OfficialControlAdapter,
    MicroTurnResult,
    build_prompt_tokens,
)

__all__ = [
    "DEFAULT_SCRIPT",
    "PromptTokens",
    "OfficialControlAdapter",
    "MicroTurnResult",
    "build_prompt_tokens",
]
