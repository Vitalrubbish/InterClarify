"""Minimal T3/T4 link check: drive one X-Talk session end to end.

Starts the X-Talk FastAPI app from a runtime config (which points at the
external ASR / LLM / turn-detector / TTS services), then acts as the frontend
client: it sends ``vad_speech_start``, streams a 16 kHz mono WAV as PCM16 binary
frames, sends ``vad_speech_end``, simulates playback of the received TTS audio,
and records the observed event timeline.

Two scenarios are supported:

* sequential (default): ``--rounds`` turns run one after another.
* barge-in (``--barge-in``): a long first turn starts playing, then a second
  utterance is streamed while the reply is still playing, so the turn detector
  must stop the reply (``stop_tts``) and the following turn must complete.

The client protocol follows ``serving/modules/input_gateway.py`` and
``serving/modules/output_gateway.py``: text frames are JSON with an ``action``
field, binary frames are raw PCM16 audio. This is a headless replay, so it
drives turn boundaries through explicit client VAD events (the documented
equivalent of the browser VAD) and needs no backend VAD model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import socket
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import requests


FRAME_SAMPLES = 512
SAMPLE_RATE = 16000
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE


def _load_pcm16(path: Path, target_rate: int = SAMPLE_RATE) -> bytes:
    """Load a WAV file as mono 16 kHz PCM16 bytes."""
    import soundfile as sf
    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != target_rate:
        import soxr

        audio = soxr.resample(audio, rate, target_rate)
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def _pick_free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(config: dict, host: str, port: int) -> None:
    """Run the X-Talk FastAPI app in a dedicated process.

    Startup progress and failures also land in ``$XTALK_SERVE_LOG`` (default
    ``xtalk_serve.log``): without it a server that dies or stalls before binding
    its port leaves the caller with nothing but "server did not start in time"
    and no way to tell a crash from a stall (observed 2026-10-15).
    """
    import logging
    handler = logging.FileHandler(str(_serve_log_path()) + '.latency.log')
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.addFilter(lambda record: str(record.msg).startswith('latency_'))
    for name in ('xtalk.duplex_control.runtime_adapter', 'xtalk.duplex_control.model_client',
                 'xtalk.models.tts.kokoro_segmented'):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    _note_serve(f"start host={host} port={port}")
    try:
        import uvicorn
        from fastapi import FastAPI

        from xtalk.api import Xtalk

        _note_serve("imports ok")
        app = FastAPI(title="xtalk-link-check")
        Xtalk.from_config(config).mount_routes(app)
        _note_serve("app mounted")
        uvicorn.run(app, host=host, port=port, log_level="warning", lifespan="off")
        _note_serve("uvicorn returned")
    except BaseException:
        _note_serve("FAILED:\n" + traceback.format_exc())
        raise


def _serve_log_path() -> Path:
    """Return the file the spawned server process reports progress to."""
    return Path(os.environ.get("XTALK_SERVE_LOG", "xtalk_serve.log"))


def _note_serve(message: str) -> None:
    """Append one startup note from the spawned server process."""
    try:
        with _serve_log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"[serve {os.getpid()}] {message}\n")
    except OSError:
        pass


async def _wait(predicate, timeout: float) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.1)
    return predicate()


class LinkClient:
    """Drive one WebSocket session and record its event timeline."""

    def __init__(self, http_base: str, ws_base: str, timeout: float) -> None:
        self._http_base = http_base
        self._ws_base = ws_base
        self._timeout = timeout
        self._events: list[dict] = []
        self._audio_bytes = 0
        self._started = 0.0
        self._asr_final: str | None = None
        self._response: str = ""
        self._first_audio: float | None = None
        self._start_resp_ids: list[str] = []
        self._finish_resp_ids: list[str] = []
        self._stop_tts_count = 0
        self._stop_resp_ids: list[str] = []
        self._current_response_id: str | None = None
        self._audio_by_response: dict[str, int] = {}
        self._audio_before_finished: set[str] = set()
        self._tts_finished_ids: set[str] = set()
        self._errors: list[str] = []
        self._receiver: asyncio.Task | None = None
        self._acoustic_vad_enabled = True
        self._session_attached = asyncio.Event()

    async def run(
        self,
        audio_pcm: bytes,
        rounds: int,
        *,
        barge_pcm: bytes | None = None,
        barge_after_seconds: float = 15.0,
    ) -> dict:
        """Run the requested scenario and return a summary."""
        import websockets

        if rounds < 1:
            raise ValueError("rounds must be positive")
        token = await asyncio.to_thread(self._login)
        url = f"{self._ws_base}?access_token={token}"
        async with websockets.connect(url, max_size=None) as ws:
            receiver = asyncio.create_task(self._receive(ws))
            self._receiver = receiver
            await ws.send(json.dumps({"action": "attach_session", "session_id": None}))
            await asyncio.wait_for(self._session_attached.wait(), self._timeout)
            await asyncio.sleep(2.0)
            self._started = time.monotonic()
            if barge_pcm is not None:
                summary = await self._run_barge_in(ws, audio_pcm, barge_pcm, barge_after_seconds)
            else:
                turns = []
                for index in range(rounds):
                    turns.append(await self._run_turn(ws, audio_pcm, index))
                    if not turns[-1]["response_finished"] or self._errors:
                        break
                summary = {"rounds": turns}
            await asyncio.sleep(2.0)
            await self._wait_for(lambda: True, 0)
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        if barge_pcm is not None:
            passed = all(summary[key] for key in (
                "playback_started", "barge_in_stop_observed", "continuation_finished"
            ))
        else:
            passed = len(summary["rounds"]) == rounds and all(
                turn["response_finished"] and turn["audio_received"]
                and turn["audio_before_tts_finished"] for turn in summary["rounds"]
            )
        return {
            "status": "COMPLETE" if passed and not self._errors else "FAILED",
            "errors": self._errors,
            "playback_mode": "immediate_headless_ack",
            **summary,
            "asr_final": self._asr_final,
            "response": self._response,
            "first_audio_seconds": self._first_audio,
            "tts_audio_bytes": self._audio_bytes,
            "event_count": len(self._events),
            "events": self._events,
        }

    async def _wait_for(self, predicate, timeout: float) -> bool:
        """Wait for an event while observing receiver failures and errors."""
        def ready_or_failed():
            """Stop waiting if the receiver closes or the server reports an error."""
            if self._receiver is not None and self._receiver.done():
                error = self._receiver.exception() if not self._receiver.cancelled() else None
                message = f"receiver failed: {error}" if error else "receiver closed"
                if message not in self._errors:
                    self._errors.append(message)
            return bool(self._errors) or predicate()
        await _wait(ready_or_failed, timeout)
        return not self._errors and bool(predicate())

    async def _send_turn_input(
        self,
        ws: websockets.WebSocketClientProtocol,
        audio_pcm: bytes,
        index: int,
    ) -> tuple[float, float]:
        """Stream PCM using negotiated VAD capability; return input timestamps."""
        started = time.monotonic()
        if self._acoustic_vad_enabled:
            await ws.send(json.dumps({"action": "vad_speech_start"}))
        self._record("vad_speech_start" if self._acoustic_vad_enabled else "audio_input_start", index)
        frames = [
            audio_pcm[i : i + FRAME_BYTES]
            for i in range(0, len(audio_pcm), FRAME_BYTES)
        ]
        for offset, frame in enumerate(frames):
            target = offset * FRAME_SECONDS
            now = time.monotonic() - started
            if target > now:
                await asyncio.sleep(target - now)
            if len(frame) < FRAME_BYTES:
                frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
            await ws.send(frame)
        if self._acoustic_vad_enabled:
            await ws.send(json.dumps({"action": "vad_speech_end"}))
        user_end = time.monotonic()
        self._record("vad_speech_end" if self._acoustic_vad_enabled else "audio_input_end", index)
        return started, user_end

    async def _run_turn(
        self,
        ws: websockets.WebSocketClientProtocol,
        audio_pcm: bytes,
        index: int,
    ) -> dict:
        starts_before = len(self._start_resp_ids)
        started, user_end = await self._send_turn_input(ws, audio_pcm, index)
        completed = await self._wait_for(
            lambda: any(rid in self._finish_resp_ids
                        for rid in self._start_resp_ids[starts_before:]), self._timeout
        )
        new_ids = self._start_resp_ids[starts_before:]
        response_id = new_ids[0] if new_ids else None
        return {
            "index": index,
            "audio_seconds": len(audio_pcm) / (2 * SAMPLE_RATE),
            "user_end_seconds": user_end - started,
            "response_id": response_id,
            "response_finished": completed and response_id in self._finish_resp_ids,
            "audio_received": self._audio_by_response.get(response_id, 0) > 0,
            "audio_before_tts_finished": response_id in self._audio_before_finished,
            "first_audio_seconds": self._first_audio,
        }

    async def _run_barge_in(
        self,
        ws: websockets.WebSocketClientProtocol,
        request_pcm: bytes,
        barge_pcm: bytes,
        after_seconds: float,
    ) -> dict:
        """Play a long reply, interrupt it mid-playback, then let a turn finish."""
        a_start, a_end = await self._send_turn_input(ws, request_pcm, 0)
        playback_started = await self._wait_for(lambda: self._audio_bytes > 0, 90.0)
        await asyncio.sleep(max(0.0, after_seconds))
        bytes_before = self._audio_bytes
        interrupted_id = self._current_response_id
        active_before_barge = interrupted_id is not None and interrupted_id not in self._finish_resp_ids
        starts_before = len(self._start_resp_ids)

        b_start, b_end = await self._send_turn_input(ws, barge_pcm, 1)

        stopped = await self._wait_for(
            lambda: interrupted_id in self._stop_resp_ids, self._timeout
        )
        completed = await self._wait_for(
            lambda: len(self._start_resp_ids) > starts_before
            and self._start_resp_ids[starts_before] in self._finish_resp_ids,
            self._timeout,
        )
        continuation_id = (self._start_resp_ids[starts_before]
                           if len(self._start_resp_ids) > starts_before else None)
        return {
            "scenario": "barge_in",
            "request_audio_seconds": len(request_pcm) / (2 * SAMPLE_RATE),
            "request_user_end_seconds": a_end - a_start,
            "barge_in_audio_seconds": len(barge_pcm) / (2 * SAMPLE_RATE),
            "barge_in_user_end_seconds": b_end - b_start,
            "barge_in_after_playback_seconds": after_seconds,
            "playback_started": playback_started and active_before_barge,
            "interrupted_response_id": interrupted_id,
            "continuation_response_id": continuation_id,
            "barge_in_stop_observed": stopped and active_before_barge,
            "continuation_finished": completed and self._audio_by_response.get(continuation_id, 0) > 0
            and continuation_id in self._audio_before_finished,
            "tts_audio_after_barge_in": self._audio_bytes - bytes_before,
            "first_audio_seconds": self._first_audio,
        }

    async def _receive(self, ws: websockets.WebSocketClientProtocol) -> None:
        async for message in ws:
            if isinstance(message, bytes):
                if self._first_audio is None:
                    self._first_audio = time.monotonic() - self._started
                self._audio_bytes += len(message)
                rid = self._current_response_id
                if rid is None:
                    self._errors.append("audio received without start_tts response ID")
                    continue
                self._audio_by_response[rid] = self._audio_by_response.get(rid, 0) + len(message)
                if rid not in self._tts_finished_ids:
                    self._audio_before_finished.add(rid)
                await ws.send(json.dumps({"action": "tts_chunk_played", "response_id": rid}))
                continue
            payload = json.loads(message)
            action = payload.get("action")
            data = payload.get("data")
            if action == "session_attached" and isinstance(data, dict):
                self._acoustic_vad_enabled = data.get("acoustic_vad_enabled", True)
                self._session_attached.set()
            self._record(action, None, data)
            if action == "finish_asr" and isinstance(data, dict):
                self._asr_final = data.get("text")
            elif action == "update_resp" and isinstance(data, dict):
                self._response = str(data.get("text", ""))
            elif action == "start_tts" and isinstance(data, dict):
                if data.get("response_id"):
                    self._current_response_id = str(data["response_id"])
                    self._start_resp_ids.append(self._current_response_id)
            elif action == "finish_resp" and isinstance(data, dict):
                self._response = str(data.get("text", self._response))
                if data.get("response_id"):
                    self._finish_resp_ids.append(str(data["response_id"]))
            elif action == "stop_tts":
                self._stop_tts_count += 1
                if isinstance(data, dict) and data.get("response_id"):
                    self._stop_resp_ids.append(str(data["response_id"]))
            elif action == "tts_finished":
                rid = str(data.get("response_id", "")) if isinstance(data, dict) else ""
                self._tts_finished_ids.add(rid)
                await ws.send(json.dumps({"action": "tts_playback_finished", "response_id": rid}))
            elif action == "error":
                self._errors.append(str(data or payload))

    def _record(self, action: str | None, index: int | None, data: object = None) -> None:
        entry = {"action": action, "seconds": time.monotonic() - self._started}
        if index is not None:
            entry["round"] = index
        if data is not None:
            entry["data"] = data
        self._events.append(entry)

    def _login(self) -> str:
        response = requests.post(f"{self._http_base}/api/auth/login", timeout=10)
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("login did not return access_token")
        return str(token)


async def _poll_port(host: str, port: int, deadline: float) -> None:
    """Wait until the server port accepts connections."""
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) == 0:
                return
        await asyncio.sleep(0.1)
    raise TimeoutError("X-Talk server did not start in time")


def _server_failure_detail(server: Any) -> str:
    """Describe how the spawned server process ended, or that it is stuck."""
    if server.is_alive():
        return f"server process {server.pid} is still alive (stalled before binding its port)"
    return f"server process {server.pid} exited with code {server.exitcode}"


async def _wait_for_server(server: Any, port: int, deadline: float) -> None:
    """Wait for the spawned server, reporting its fate and log when it stalls."""
    try:
        await _poll_port("127.0.0.1", port, deadline)
    except TimeoutError as error:
        log_path = _serve_log_path()
        tail = ""
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            tail = f"\n--- {log_path} (tail) ---\n{text[-2000:]}"
        raise TimeoutError(f"{error}: {_server_failure_detail(server)}{tail}") from None


def main() -> None:
    """Start the X-Talk server, run the client scenario, and write a report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--barge-in",
        action="store_true",
        help="run the barge-in scenario instead of sequential turns",
    )
    parser.add_argument(
        "--barge-in-audio",
        type=Path,
        help="WAV streamed as the interrupting utterance (required with --barge-in)",
    )
    parser.add_argument(
        "--barge-in-after-seconds",
        type=float,
        default=15.0,
        help="delay after playback starts before the interrupting utterance",
    )
    parser.add_argument(
        "--drop-turn-detector",
        action="store_true",
        help="debug only: remove turn_detector from the config (VAD end finalizes)",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.drop_turn_detector:
        config.pop("turn_detector", None)
    if args.barge_in and args.barge_in_audio is None:
        parser.error("--barge-in requires --barge-in-audio")

    port = _pick_free_port()
    ctx = multiprocessing.get_context("spawn")
    server = ctx.Process(target=_serve, args=(config, "127.0.0.1", port))
    server.start()
    try:
        asyncio.run(_poll_port("127.0.0.1", port, time.monotonic() + 30.0))
        client = LinkClient(
            http_base=f"http://127.0.0.1:{port}",
            ws_base=f"ws://127.0.0.1:{port}/ws",
            timeout=args.timeout,
        )
        report = asyncio.run(
            client.run(
                _load_pcm16(args.audio),
                rounds=args.rounds,
                barge_pcm=_load_pcm16(args.barge_in_audio) if args.barge_in else None,
                barge_after_seconds=args.barge_in_after_seconds,
            )
        )
    finally:
        server.terminate()
        server.join(timeout=10)
        if server.is_alive():
            server.kill()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "events"},
            ensure_ascii=False,
        )
    )
    if report["status"] != "COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
