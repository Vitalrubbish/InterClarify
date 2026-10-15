"""Serve the X2 adaptive online stream without offline transcription."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RecognizeRequest(BaseModel):
    """Incremental PCM; is_final is a pause hint, end_stream is EOF."""

    session_id: str
    audio: str = ""
    is_final: bool = False
    end_stream: bool = False


class X2Service:
    """Own one active online session on a shared adaptive model."""

    def __init__(self, session_factory, language: str = "en", timeout: float = 60):
        self.factory = session_factory
        self.language = language
        self.timeout = timeout
        self.lock = threading.Lock()
        self.session = None
        self.session_id = None
        self.audio_samples = 0
        self.ended = False

    def create(self) -> str:
        """Start a live session and await its model warmup."""
        with self.lock:
            if self.session is not None:
                raise RuntimeError("one active X2 session is supported")
            session = self.factory()
            session.set_language_id(self.language)
            session.start()
            deadline = time.monotonic() + self.timeout
            while not session.warmup_done:
                if session.error or time.monotonic() > deadline:
                    session.abort()
                    raise RuntimeError(session.error or "X2 warmup timeout")
                time.sleep(0.01)
            self.session = session
            self.session_id = uuid.uuid4().hex
            self.audio_samples = 0
            self.ended = False
            return self.session_id

    def recognize(self, request: RecognizeRequest) -> str:
        """Append audio and return live text directly, without prefix filtering."""
        with self.lock:
            if self.session is None or request.session_id != self.session_id:
                raise KeyError(request.session_id)
            if self.ended:
                if request.audio:
                    raise ValueError("audio after end_stream")
                return self.session.live_text
            pcm = base64.b64decode(request.audio, validate=True)
            if len(pcm) % 2:
                raise ValueError("PCM16 requires an even byte count")
            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            self.audio_samples += len(audio)
            self.session.append_pcm(audio)
            if request.end_stream:
                worker = self.session.finish_async()
                worker.join(self.timeout)
                if worker.is_alive():
                    raise RuntimeError("X2 online EOF timeout")
                self.ended = True
            if self.session.error:
                raise RuntimeError(self.session.error)
            while True:
                try:
                    event = self.session._event_q.get_nowait()
                except queue.Empty:
                    break
                if event and event["kind"] in ("live_emit", "live_done"):
                    logger.info(json.dumps({"session_id": self.session_id,
                        "delivered_monotonic": time.monotonic(), **event}))
            text = self.session.live_text
            logger.info(json.dumps({"event": "x2_online", "session_id": self.session_id,
                "audio_seconds": self.audio_samples / 16000, "text": text,
                "pause_hint": request.is_final, "end_stream": request.end_stream}))
            return text

    def close(self, session_id: str) -> None:
        """Abort and release the matching session."""
        with self.lock:
            if self.session is not None and session_id == self.session_id:
                self.session.abort()
                self.session = None
                self.session_id = None


def create_app(service: X2Service) -> FastAPI:
    """Expose the session protocol to the X-Talk HTTP adapter."""
    app = FastAPI()

    @app.get("/health")
    def health():
        """Report model readiness and online-only operation."""
        return {"status": "ok", "backend": "x2", "offline": False}

    @app.post("/v1/session")
    def create():
        """Allocate one independent decoder session."""
        try:
            return {"session_id": service.create()}
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/recognize")
    def recognize(request: RecognizeRequest):
        """Return the current online cumulative transcript."""
        try:
            return {"text": service.recognize(request), "language": service.language}
        except KeyError as exc:
            raise HTTPException(404, "unknown session") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.delete("/v1/session/{session_id}")
    def close(session_id: str):
        """Release a session without offline inference."""
        service.close(session_id)
        return {"ok": True}

    return app


def main() -> None:
    """Load the fixed official adaptive engine and serve HTTP."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", choices=("en", "zh", "cs"), default="en")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8005)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    source = args.source_root.resolve()
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != "0aca80597bb1399c0be4002de5bc62c0a779c542":
        raise RuntimeError(f"unexpected X2 source commit: {commit}")
    sys.path[:0] = [str(source / "demo"), str(source)]
    from models import build_model
    from engine_adaptive import AdaptiveSession
    import uvicorn

    wrapper = build_model("voxtral_asr").load_for_inference(
        args.model, device="cuda:0", adaptive_latency=True,
        language_tag={"enabled": True, "require_checkpoint_weights": True})
    wrapper["model"].eval()

    def factory():
        """Create an online-only, frame-synchronous decoder."""
        return AdaptiveSession(wrapper["model"], wrapper["processor"],
            enable_live=True, enable_offline=False, listen_chunk_size=1, verbose=False)

    logger.info("X2 source=%s model=%s language=%s offline=false", commit, args.model, args.language)
    uvicorn.run(create_app(X2Service(factory, args.language)), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
