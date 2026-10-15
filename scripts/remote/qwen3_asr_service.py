"""Local streaming HTTP service that wraps the official Qwen3-ASR vLLM API.

The X-Talk adapter (`Qwen3ASRClient`) sends 16 kHz mono PCM16 bytes and reads
cumulative transcripts. This service keeps one streaming state per
``session_id`` so a session can be fed incrementally; the model runs in the
isolated ASR conda environment, never in the X-Talk client environment.

``qwen_asr`` re-decodes the trailing ``unfixed_token_num`` tokens of its carried
prefix on every chunk, so the raw transcript can *replace* text it already
emitted. The released DuplexCascade server never sees that: it consumes Kyutai's
finalized words only and ignores the streaming hypotheses. With
``--emit-committed-prefix`` this service reproduces that contract by returning
only text the decoder has committed to, which makes consecutive transcripts
strictly extend each other. The committed stream is tracked as a *token* prefix:
the raw transcript is re-decoded from scratch on every chunk, so its punctuation
and spacing can differ from an earlier decode even when the words are unchanged,
and comparing tokens is what keeps the stream advancing instead of stalling on
the first such difference. ``is_final`` releases the remaining tail, and the next
response continues from the released text.

Protocol (HTTP/JSON):
  POST   /v1/session            -> {"session_id": str}
  POST   /v1/recognize          -> {"text": str, "language": str}
         body {"session_id", "audio": base64(PCM16LE), "is_final": bool}
  DELETE /v1/session/{id}       -> {"ok": true}
  GET    /health                -> {"status": "ok"}
"""

from __future__ import annotations

import argparse
import base64
import logging
import threading
import uuid

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RecognizeRequest(BaseModel):
    """One incremental recognition request for an existing session."""

    session_id: str
    audio: str = ""
    is_final: bool = False


class SessionState:
    """Streaming decoder state, its serialization lock and the visible prefix."""

    def __init__(self, state: object) -> None:
        self.state = state
        self.lock = threading.Lock()
        # Token ids already handed to the caller, the text they decode to, and how
        # often a decoder revision tried to change text that was already released.
        self.committed_ids: list[int] = []
        self.visible_text = ""
        self.stalls = 0


def committed_token_ids(model: object, text: str, token_count: int) -> list[int]:
    """Return the token ids of ``text`` outside the decoder's revision window.

    ``qwen_asr`` re-decodes the last ``unfixed_token_num`` tokens of the carried
    prefix on every chunk, so only those can still change; everything before them
    has been decided.

    Parameters
    ----------
    model : object
        ``Qwen3ASRModel`` instance owning the streaming processor.
    text : str
        Parsed transcript (``state.text``). The parsed form is used rather than the
        raw decode so the ``language X<asr_text>`` header stays out of the result.
    token_count : int
        Number of trailing tokens that may still be revised.

    Returns
    -------
    list of int
        Token ids the decoder has committed to, possibly empty.
    """
    ids = list(model.processor.tokenizer.encode(text))
    end = len(ids) - int(token_count)
    return ids[:end] if end > 0 else []


def decode_token_prefix(model: object, ids: list[int]) -> str:
    """Decode a token prefix, backing off a trailing partially decoded character."""
    tokenizer = model.processor.tokenizer
    end = len(ids)
    while end > 0:
        text = tokenizer.decode(ids[:end])
        if "\ufffd" not in text:
            return text
        end -= 1
    return ""


def advance_committed(
    model: object,
    text: str,
    token_count: int,
    committed_ids: list[int],
    visible_text: str,
) -> tuple[list[int], str, bool]:
    """Return the next monotone ``(committed token ids, visible text)`` pair.

    The committed stream is a *token* prefix, never a string prefix. The raw
    transcript is re-decoded from scratch on every chunk, so its punctuation and
    spacing can differ from a previous decode even when the words are unchanged;
    a string comparison stalls forever on the first such difference, while a token
    comparison keeps the stream advancing.

    Only the trailing ``token_count`` tokens are held back, because those are the
    only ones the decoder may still rewrite. The held-back tail is released by the
    caller's *explicit* boundary (``is_final``), never by "the decode did not
    change since the last call": a pause inside a sentence is not the end of the
    user's segment, and releasing there is what used to hand the runtime a
    truncated transcript it could never extend.

    A revision deeper than the advertised window cannot be taken back, so the
    already-visible text is kept untouched and the commit resumes once the decoder
    agrees again; the returned flag reports that case for monitoring.

    Parameters
    ----------
    model : object
        ``Qwen3ASRModel`` instance owning the streaming processor.
    text : str
        Parsed transcript of the current decode (``state.text``).
    token_count : int
        Number of trailing tokens that may still be revised.
    committed_ids : list of int
        Token ids already handed to the caller.
    visible_text : str
        Text already handed to the caller.

    Returns
    -------
    tuple of (list of int, str, bool)
        Updated ``(committed_ids, visible_text, stalled)``.
    """
    proposed = committed_token_ids(model, text, token_count)
    common = min(len(proposed), len(committed_ids))
    if proposed[:common] != list(committed_ids)[:common]:
        # The decoder revised a token that was already handed out. It cannot be
        # taken back, so the released text stays untouched and the commit waits.
        return committed_ids, visible_text, True
    if len(proposed) <= len(committed_ids):
        return committed_ids, visible_text, False
    return proposed, decode_token_prefix(model, proposed), False



class ASRService:
    """Own the ASR model and the per-session streaming states."""

    def __init__(
        self,
        model_path: str,
        gpu_memory_utilization: float,
        max_new_tokens: int,
        chunk_size_sec: float,
        unfixed_chunk_num: int,
        unfixed_token_num: int,
        emit_committed_prefix: bool = False,
    ) -> None:
        from qwen_asr import Qwen3ASRModel

        self.model = Qwen3ASRModel.LLM(
            model=model_path,
            gpu_memory_utilization=gpu_memory_utilization,
            max_new_tokens=max_new_tokens,
        )
        self.streaming_kwargs = {
            "chunk_size_sec": chunk_size_sec,
            "unfixed_chunk_num": unfixed_chunk_num,
            "unfixed_token_num": unfixed_token_num,
        }
        # Hiding the revision window is what makes the transcript the runtime
        # sees append-only, like the released server's finalized-word stream.
        self.emit_committed_prefix = bool(emit_committed_prefix)
        self.hidden_token_num = int(unfixed_token_num)
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def create_session(self) -> str:
        """Create and register a new streaming session."""
        state = self.model.init_streaming_state(**self.streaming_kwargs)
        session_id = uuid.uuid4().hex
        with self._lock:
            self._sessions[session_id] = SessionState(state)
        return session_id

    def delete_session(self, session_id: str) -> None:
        """Release a session; unknown ids are ignored."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def recognize(self, request: RecognizeRequest) -> tuple[str, str]:
        """Feed audio into one session and return its cumulative transcript.

        When ``emit_committed_prefix`` is enabled the response holds only text the
        streaming decoder has committed to, so consecutive responses can only
        extend each other. Only the decoder's revision window (its trailing
        ``unfixed_token_num`` tokens) is held back; ``is_final`` releases the whole
        transcript, and the next response continues from the released text.
        """
        with self._lock:
            session = self._sessions.get(request.session_id)
        if session is None:
            raise KeyError(request.session_id)

        pcm = np.frombuffer(base64.b64decode(request.audio), dtype=np.int16)
        samples = pcm.astype(np.float32) / 32768.0
        with session.lock:
            if samples.size:
                self.model.streaming_transcribe(samples, session.state)
            # is_final is a temporary boundary: flush the tail so the caller can
            # read more text, but keep the session for further audio.
            if request.is_final:
                self.model.finish_streaming_transcribe(session.state)
                text = session.state.text or ""
                session.visible_text = text
                session.committed_ids = committed_token_ids(self.model, text, 0)
            elif self.emit_committed_prefix:
                session.committed_ids, session.visible_text, stalled = advance_committed(
                    self.model, session.state.text or "", self.hidden_token_num,
                    session.committed_ids, session.visible_text)
                if stalled:
                    session.stalls += 1
                    if session.stalls == 1:
                        logger.warning(
                            "ASR revision reached text already released; the "
                            "committed transcript holds its monotone prefix")
                text = session.visible_text
            else:
                text = session.state.text or ""
            language = getattr(session.state, "language", "") or ""
        return text, language


def build_app(service: ASRService) -> FastAPI:
    """Build the FastAPI application bound to one ASR service."""
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/session")
    def create_session() -> dict[str, str]:
        return {"session_id": service.create_session()}

    @app.delete("/v1/session/{session_id}")
    def delete_session(session_id: str) -> dict[str, bool]:
        service.delete_session(session_id)
        return {"ok": True}

    @app.post("/v1/recognize")
    def recognize(request: RecognizeRequest) -> dict[str, str]:
        try:
            text, language = service.recognize(request)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown session")
        return {"text": text, "language": language}

    return app


def main() -> None:
    """Parse arguments, load the model once, and serve requests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8005)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.75)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--chunk-size-sec", type=float, default=0.6)
    parser.add_argument("--unfixed-chunk-num", type=int, default=2)
    parser.add_argument("--unfixed-token-num", type=int, default=5)
    parser.add_argument("--emit-committed-prefix", action="store_true",
                        help="return only text the streaming decoder has committed to, "
                             "so consecutive responses can only extend each other")
    args = parser.parse_args()

    service = ASRService(
        model_path=args.model,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_new_tokens=args.max_new_tokens,
        chunk_size_sec=args.chunk_size_sec,
        unfixed_chunk_num=args.unfixed_chunk_num,
        unfixed_token_num=args.unfixed_token_num,
        emit_committed_prefix=args.emit_committed_prefix,
    )
    uvicorn.run(build_app(service), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
