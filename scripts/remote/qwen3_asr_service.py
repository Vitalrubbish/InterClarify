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
strictly extend each other. ``is_final`` releases the remaining tail, and the
next response continues from the released text.

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
import threading
import uuid

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


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
        # Last parsed transcript the decoder produced, and the text already handed
        # to the caller. The visible transcript may only ever extend the latter.
        self.last_parsed = ""
        self.visible_text = ""


def truncate_tokens(model: object, text: str, token_count: int) -> str:
    """Drop the trailing tokens a streaming decoder may still revise.

    ``qwen_asr`` re-decodes the last ``unfixed_token_num`` tokens of the carried
    prefix on every chunk, so those tokens are the only ones that can still
    change. Removing them leaves text the decoder has committed to.

    Parameters
    ----------
    model : object
        ``Qwen3ASRModel`` instance owning the streaming processor.
    text : str
        Parsed transcript (``state.text``). Truncating the parsed form rather
        than the raw decode keeps the ``language X<asr_text>`` header out of the
        result when the cut lands inside it.
    token_count : int
        Number of trailing tokens that may still be revised.

    Returns
    -------
    str
        Committed prefix, or an empty string when nothing is committed yet.
    """
    tokenizer = model.processor.tokenizer
    ids = tokenizer.encode(text)
    end = len(ids) - int(token_count)
    while end > 0:
        prefix = tokenizer.decode(ids[:end])
        if "\ufffd" not in prefix:
            return prefix
        end -= 1
    return ""


def advance_committed(
    model: object,
    state: object,
    token_count: int,
    last_parsed: str,
    visible_text: str,
) -> tuple[str, str]:
    """Return the next monotone visible ``(last_parsed, text)`` pair of one stream.

    While the recognizer keeps producing new text, its last ``token_count`` tokens
    may still be rewritten, so they are held back: that is what stops a micro-turn
    from carrying a question the user is still in the middle of saying. A decode
    step that adds no new transcript (a pause, silence, or the end of an utterance)
    leaves nothing to revise, so the held-back tail is released -- the moment
    Kyutai's word stream would have committed those words too. The visible text is
    only ever extended, never replaced.

    Parameters
    ----------
    model : object
        ``Qwen3ASRModel`` instance owning the streaming processor.
    state : object
        ``ASRStreamingState`` of the current session.
    token_count : int
        Number of trailing tokens that may still be revised.
    last_parsed : str
        Transcript the decoder returned on the previous call.
    visible_text : str
        Text already handed to the caller.

    Returns
    -------
    tuple of (str, str)
        Updated ``(last_parsed, visible_text)``.
    """
    parsed = state.text or ""
    if parsed == last_parsed:
        proposed = parsed
    else:
        proposed = truncate_tokens(model, parsed, token_count)
    if not proposed.startswith(visible_text):
        return parsed, visible_text
    return parsed, proposed



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
        extend each other. A decode step that adds no new transcript releases the
        held-back tail, and ``is_final`` releases the whole transcript; the next
        response continues from the released text in both cases.
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
                session.last_parsed = text
                session.visible_text = text
            elif self.emit_committed_prefix:
                session.last_parsed, session.visible_text = advance_committed(
                    self.model, session.state, self.hidden_token_num,
                    session.last_parsed, session.visible_text)
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
