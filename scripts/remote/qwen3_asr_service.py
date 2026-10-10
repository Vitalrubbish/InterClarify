"""Local streaming HTTP service that wraps the official Qwen3-ASR vLLM API.

The X-Talk adapter (`Qwen3ASRClient`) sends 16 kHz mono PCM16 bytes and reads
cumulative transcripts. This service keeps one streaming state per
``session_id`` so a session can be fed incrementally; the model runs in the
isolated ASR conda environment, never in the X-Talk client environment.

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
    """Streaming decoder state and its serialization lock."""

    def __init__(self, state: object) -> None:
        self.state = state
        self.lock = threading.Lock()


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
        """Feed audio into one session and return its cumulative transcript."""
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
    args = parser.parse_args()

    service = ASRService(
        model_path=args.model,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_new_tokens=args.max_new_tokens,
        chunk_size_sec=args.chunk_size_sec,
        unfixed_chunk_num=args.unfixed_chunk_num,
        unfixed_token_num=args.unfixed_token_num,
    )
    uvicorn.run(build_app(service), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
