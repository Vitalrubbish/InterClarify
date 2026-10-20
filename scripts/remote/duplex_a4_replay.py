#!/usr/bin/env python3
"""Replay real audio through the X-Talk DuplexCascade A4 runtime."""
from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import shutil
import sys
import time
import wave
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from xtalk_link_check import (
    LinkClient,
    _load_pcm16,
    _pick_free_port,
    _serve,
    _wait_for_server,
)

SAMPLE_RATE = 16_000
SCENARIOS = ("normal", "interruption", "long_session", "pause", "multi_question")
# Acoustic settle window: after the reset, the interrupted response must stay silent.
INTERRUPTION_SETTLE_SECONDS = 1.0
# Reset reasons written by the adapter: the released speaking window opened.
INTERRUPTION_STOP_REASONS = ("<|user interruption|>", "<|user is talking|>")
# Teardown reasons: the session closed or inference failed, which is not an interruption.
TEARDOWN_STOP_REASONS = ("shutdown", "cancelled", "protocol_error", "model_service_error")


class TimedPcmCapture:
    """Write played PCM on a session-relative wall-clock timeline."""

    def __init__(self, path: Path, sample_rate: int) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.frames = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self.output = wave.open(str(path), "wb")
        self.output.setnchannels(1)
        self.output.setsampwidth(2)
        self.output.setframerate(sample_rate)

    def append(self, pcm: bytes, start_seconds: float) -> None:
        """Append one chunk after padding any elapsed playback gap."""
        target = max(0, round(start_seconds * self.sample_rate))
        if target > self.frames:
            self.output.writeframes(b"\x00\x00" * (target - self.frames))
            self.frames = target
        self.output.writeframes(pcm)
        self.frames += len(pcm) // 2

    def pad_to(self, seconds: float) -> None:
        """Pad the capture to at least one requested duration."""
        target = max(0, round(seconds * self.sample_rate))
        if target > self.frames:
            self.output.writeframes(b"\x00\x00" * (target - self.frames))
            self.frames = target

    def close(self) -> None:
        """Flush the WAV header and close the output."""
        self.output.close()


class A4ReplayClient(LinkClient):
    """Headless client that also stores the received PCM as a WAV file."""

    def __init__(
        self,
        http_base: str,
        ws_base: str,
        timeout: float,
        output_wav: Path,
        output_rate: int = 48_000,
        fdb_tail_seconds: float = 5.0,
        fdb_tail_audio: bool = False,
    ) -> None:
        super().__init__(http_base, ws_base, timeout)
        self.output_wav = output_wav
        self.output_rate = output_rate
        self.fdb_tail_seconds = fdb_tail_seconds
        self.fdb_tail_audio = fdb_tail_audio
        self._pcm_received_ids: set[str] = set()
        self._playback_started_ids: set[str] = set()
        self.session_id: str | None = None
        self._capture: TimedPcmCapture | None = None
        self._playback_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self._playback_task: asyncio.Task[None] | None = None
        self._stopped_ids: set[str] = set()
        self._outstanding: dict[str, int] = {}
        self._finish_pending: set[str] = set()
        self._playing: tuple[str, bytes, float] | None = None
        self._stop_signal = asyncio.Event()

    def _capture_played(self, response_id: str, pcm: bytes, started: float) -> None:
        """Retain only PCM that crossed the simulated playback boundary."""
        if not pcm:
            return
        if self._first_audio is None:
            self._first_audio = started - self._started
        if self._capture is not None:
            self._capture.append(pcm, started - self._started)
        self._audio_bytes += len(pcm)
        self._audio_by_response[response_id] = self._audio_by_response.get(response_id, 0) + len(pcm)

    async def run(
        self,
        audio_pcm: bytes,
        rounds: int,
        *,
        scenario: str = "normal",
        barge_pcm: bytes | None = None,
        barge_after_seconds: float = 2.0,
        pause_pcm: bytes | None = None,
        pause_gap_seconds: float = 1.5,
    ) -> dict:
        """Run one A4 scenario with protocol-specific completion criteria."""
        import websockets

        self.output_wav.parent.mkdir(parents=True, exist_ok=True)
        self._capture = TimedPcmCapture(self.output_wav, self.output_rate)
        try:
            token = await asyncio.to_thread(self._login)
            url = f"{self._ws_base}?access_token={token}"
            async with websockets.connect(url, max_size=None) as ws:
                receiver = asyncio.create_task(self._receive(ws))
                self._receiver = receiver
                await ws.send(
                    json.dumps({"action": "attach_session", "session_id": None})
                )
                await asyncio.wait_for(self._session_attached.wait(), self._timeout)
                await asyncio.sleep(2.0)
                self._started = time.monotonic()
                if scenario == "interruption":
                    if barge_pcm is None:
                        raise ValueError("interruption scenario requires barge-in PCM")
                    result, passed = await self._run_interruption(
                        ws,
                        audio_pcm,
                        barge_pcm,
                        barge_after_seconds,
                    )
                elif scenario == "long_session":
                    result, passed = await self._run_long_session(
                        ws,
                        audio_pcm,
                        rounds,
                    )
                elif scenario == "pause":
                    if pause_pcm is None:
                        raise ValueError("pause scenario requires a second PCM segment")
                    result, passed = await self._run_pause(
                        ws,
                        audio_pcm,
                        pause_pcm,
                        pause_gap_seconds,
                    )
                elif scenario == "multi_question":
                    result, passed = await self._run_multi_question(ws, audio_pcm)
                elif scenario == "fdb":
                    result, passed = await self._run_fdb(ws, audio_pcm)
                else:
                    turn = await self._run_turn(ws, audio_pcm, 0)
                    result = {"rounds": [turn]}
                    passed = bool(
                        turn["response_finished"]
                        and turn["audio_received"]
                        and turn["audio_before_tts_finished"]
                    )
                await asyncio.sleep(0.5)
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
            report = {
                "status": "COMPLETE" if passed and not self._errors else "FAILED",
                "errors": self._errors,
                **result,
                "asr_final": self._asr_final,
                "response": self._response,
                "first_audio_seconds": self._first_audio,
                "tts_audio_bytes": self._audio_bytes,
                "played_audio_by_response": dict(self._audio_by_response),
                "event_count": len(self._events),
                "events": self._events,
            }
        finally:
            if self._playback_task is not None:
                self._playback_task.cancel()
                await asyncio.gather(self._playback_task, return_exceptions=True)
                self._playback_task = None
            if self._capture is not None:
                if self._started > 0:
                    self._capture.pad_to(max(0.0, time.monotonic() - self._started))
                self._capture.close()
                self._capture = None
        report["output_wav"] = str(self.output_wav)
        report["output_sample_rate"] = self.output_rate
        report["session_id"] = self.session_id
        report["playback_mode"] = "paced_headless_ack"
        report["tts_audio_bytes"] = self._audio_bytes
        report["played_audio_by_response"] = dict(self._audio_by_response)
        report["first_audio_seconds"] = self._first_audio
        return report

    async def _run_fdb(
        self,
        ws: Any,
        audio_pcm: bytes,
    ) -> tuple[dict[str, Any], bool]:
        """Stream one complete FDB input without requiring the system to answer."""
        replay_pcm = audio_pcm
        if self.fdb_tail_audio:
            replay_pcm += b'\x00\x00' * round(SAMPLE_RATE * self.fdb_tail_seconds)
        started, ended = await self._send_turn_input(ws, replay_pcm, 0)
        if not self.fdb_tail_audio:
            await asyncio.sleep(self.fdb_tail_seconds)
        result = {
            "scenario": "fdb",
            "input_start_seconds": started - self._started,
            "diagnostic_tail_seconds": self.fdb_tail_seconds,
            "diagnostic_tail_audio": self.fdb_tail_audio,
            "input_audio_seconds": len(audio_pcm) / (2 * SAMPLE_RATE),
            "send_seconds": ended - started,
            "response_ids": list(self._start_resp_ids),
            "finished_response_ids": list(self._finish_resp_ids),
        }
        return result, not self._errors

    async def _run_interruption(
        self,
        ws: Any,
        request_pcm: bytes,
        interruption_pcm: bytes,
        after_seconds: float,
    ) -> tuple[dict[str, Any], bool]:
        """Require the active response to stop without requiring a new answer.

        The event check confirms the interruption reset, and the acoustic check
        confirms the interrupted response stops receiving audio afterwards.
        """
        request_start, request_end = await self._send_turn_input(ws, request_pcm, 0)
        playback_started = await self._wait_for(
            lambda: self._audio_bytes > 0 and self._current_response_id is not None,
            self._timeout,
        )
        await asyncio.sleep(max(0.0, after_seconds))
        interrupted_id = self._current_response_id
        active = bool(
            interrupted_id
            and interrupted_id not in self._finish_resp_ids
            and interrupted_id not in self._stop_resp_ids
        )
        bytes_before = self._audio_bytes
        interruption_start, interruption_end = await self._send_turn_input(
            ws,
            interruption_pcm,
            1,
        )
        # Bound the wait on the interrupted response reaching a terminal state, so a
        # scenario whose answer already ended cannot stall for the full timeout.
        await self._wait_for(
            lambda: interrupted_id in self._stop_resp_ids
            or interrupted_id in self._finish_resp_ids,
            self._timeout,
        )
        stopped = interrupted_id in self._stop_resp_ids
        audio_at_stop = 0
        audio_after_stop = 0
        if stopped:
            await asyncio.sleep(INTERRUPTION_SETTLE_SECONDS / 20)
            audio_at_stop = self._audio_by_response.get(interrupted_id, 0)
            await asyncio.sleep(INTERRUPTION_SETTLE_SECONDS)
            audio_after_stop = self._audio_by_response.get(interrupted_id, 0) - audio_at_stop
        frozen = bool(stopped and audio_after_stop <= 0)
        result = {
            "scenario": "interruption",
            "request_audio_seconds": len(request_pcm) / (2 * SAMPLE_RATE),
            "request_user_end_seconds": request_end - request_start,
            "interruption_audio_seconds": len(interruption_pcm) / (2 * SAMPLE_RATE),
            "interruption_user_end_seconds": interruption_end - interruption_start,
            "interruption_after_playback_seconds": after_seconds,
            "playback_started": bool(playback_started and active),
            "interrupted_response_id": interrupted_id,
            "interruption_stop_observed": bool(stopped and active),
            "interrupted_response_audio_bytes": audio_at_stop,
            "interrupted_response_audio_after_stop": audio_after_stop,
            "interrupted_audio_frozen": frozen,
            "played_audio_after_interruption_input": self._audio_bytes - bytes_before,
        }
        return result, bool(playback_started and active and stopped and frozen)

    async def _run_long_session(
        self,
        ws: Any,
        audio_pcm: bytes,
        rounds: int,
    ) -> tuple[dict[str, Any], bool]:
        """Feed repeated real-time audio while keeping one session and queue."""
        if rounds < 2:
            raise ValueError("long-session rounds must be at least two")
        inputs = []
        for index in range(rounds):
            started, ended = await self._send_turn_input(ws, audio_pcm, index)
            inputs.append(
                {
                    "index": index,
                    "audio_seconds": len(audio_pcm) / (2 * SAMPLE_RATE),
                    "send_seconds": ended - started,
                }
            )
            await asyncio.sleep(0.6)
        completed = await self._wait_for(
            lambda: bool(self._finish_resp_ids),
            self._timeout,
        )
        result = {
            "scenario": "long_session",
            "rounds": inputs,
            "response_ids": list(self._start_resp_ids),
            "finished_response_ids": list(self._finish_resp_ids),
            "response_finished": completed,
            "audio_received": self._audio_bytes > 0,
        }
        return result, bool(completed and self._audio_bytes > 0)

    async def _run_pause(
        self,
        ws: Any,
        first_pcm: bytes,
        second_pcm: bytes,
        gap_seconds: float,
    ) -> tuple[dict[str, Any], bool]:
        """Send a user turn in two parts and observe behavior across the gap."""
        first_start, first_end = await self._send_turn_input(ws, first_pcm, 0)
        await asyncio.sleep(max(0.0, gap_seconds))
        answered_before_continue = bool(self._finish_resp_ids)
        second_start, second_end = await self._send_turn_input(ws, second_pcm, 1)
        completed = await self._wait_for(
            lambda: bool(self._finish_resp_ids),
            self._timeout,
        )
        result = {
            "scenario": "pause",
            "first_audio_seconds": len(first_pcm) / (2 * SAMPLE_RATE),
            "second_audio_seconds": len(second_pcm) / (2 * SAMPLE_RATE),
            "first_send_seconds": first_end - first_start,
            "second_send_seconds": second_end - second_start,
            "pause_gap_seconds": gap_seconds,
            "answered_before_continue": answered_before_continue,
            "response_ids": list(self._start_resp_ids),
            "finished_response_ids": list(self._finish_resp_ids),
            "response_finished": completed,
            "audio_received": self._audio_bytes > 0,
        }
        return result, bool(completed and self._audio_bytes > 0)

    async def _run_multi_question(
        self,
        ws: Any,
        audio_pcm: bytes,
    ) -> tuple[dict[str, Any], bool]:
        """Stream one continuous two-question clip and require an answer."""
        started, ended = await self._send_turn_input(ws, audio_pcm, 0)
        completed = await self._wait_for(
            lambda: bool(self._finish_resp_ids),
            self._timeout,
        )
        result = {
            "scenario": "multi_question",
            "audio_seconds": len(audio_pcm) / (2 * SAMPLE_RATE),
            "send_seconds": ended - started,
            "response_ids": list(self._start_resp_ids),
            "finished_response_ids": list(self._finish_resp_ids),
            "response_finished": completed,
            "audio_received": self._audio_bytes > 0,
        }
        return result, bool(completed and self._audio_bytes > 0)

    async def _play_audio(self, ws: Any) -> None:
        """Pace playback acknowledgements and discard stopped response tails."""
        while True:
            response_id, pcm = await self._playback_queue.get()
            try:
                if response_id in self._stopped_ids:
                    continue
                duration = len(pcm) / (2 * self.output_rate)
                started = time.monotonic()
                if response_id not in self._playback_started_ids:
                    self._playback_started_ids.add(response_id)
                    self._record("playback_started", None, {"response_id": response_id})
                self._playing = (response_id, pcm, started)
                self._stop_signal.clear()
                try:
                    await asyncio.wait_for(self._stop_signal.wait(), timeout=duration)
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    # Preserve the heard portion when the observation window ends.
                    if response_id not in self._stopped_ids:
                        frames = min(len(pcm) // 2, max(0, int((time.monotonic() - started) * self.output_rate)))
                        self._capture_played(response_id, pcm[:frames * 2], started)
                    raise
                if response_id in self._stopped_ids:
                    continue
                self._capture_played(response_id, pcm, started)
                await ws.send(
                    json.dumps(
                        {"action": "tts_chunk_played", "response_id": response_id}
                    )
                )
            finally:
                self._playing = None
                self._outstanding[response_id] = max(
                    0, self._outstanding.get(response_id, 1) - 1
                )
                if (
                    response_id in self._finish_pending
                    and self._outstanding[response_id] == 0
                    and response_id not in self._stopped_ids
                ):
                    self._finish_pending.discard(response_id)
                    await ws.send(
                        json.dumps(
                            {
                                "action": "tts_playback_finished",
                                "response_id": response_id,
                            }
                        )
                    )
                self._playback_queue.task_done()

    async def _receive(self, ws: Any) -> None:
        """Record audio and preserve the parent client's event checks."""
        self._playback_task = asyncio.create_task(self._play_audio(ws))
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    response_id = self._current_response_id
                    if response_id is None:
                        self._errors.append(
                            "audio received without start_tts response ID"
                        )
                        continue
                    if response_id not in self._pcm_received_ids:
                        self._pcm_received_ids.add(response_id)
                        self._record("pcm_received", None, {"response_id": response_id})
                    self._outstanding[response_id] = (
                        self._outstanding.get(response_id, 0) + 1
                    )
                    if response_id not in self._tts_finished_ids:
                        self._audio_before_finished.add(response_id)
                    await self._playback_queue.put((response_id, message))
                    continue
                payload = json.loads(message)
                action, data = payload.get("action"), payload.get("data")
                self._record(action, None, data)
                if action == "session_attached" and isinstance(data, dict):
                    self.session_id = str(data.get("session_id") or "") or None
                    self._acoustic_vad_enabled = data.get("acoustic_vad_enabled", True)
                    self._session_attached.set()
                elif action == "finish_asr" and isinstance(data, dict):
                    self._asr_final = data.get("text")
                elif action == "update_resp" and isinstance(data, dict):
                    self._response = str(data.get("text", ""))
                elif (
                    action == "start_tts"
                    and isinstance(data, dict)
                    and data.get("response_id")
                ):
                    self._current_response_id = str(data["response_id"])
                    self._start_resp_ids.append(self._current_response_id)
                elif action == "finish_resp" and isinstance(data, dict):
                    self._response = str(data.get("text", self._response))
                    if data.get("response_id"):
                        self._finish_resp_ids.append(str(data["response_id"]))
                elif action == "stop_tts":
                    self._stop_tts_count += 1
                    if isinstance(data, dict) and data.get("response_id"):
                        response_id = str(data["response_id"])
                        self._stop_resp_ids.append(response_id)
                        self._stopped_ids.add(response_id)
                        played_ms = 0.0
                        if self._playing is not None and self._playing[0] == response_id:
                            _, pcm, started = self._playing
                            samples = min(len(pcm) // 2, max(0, int((time.monotonic() - started) * self.output_rate)))
                            self._capture_played(response_id, pcm[:samples * 2], started)
                            played_ms = samples * 1000.0 / self.output_rate
                            self._stop_signal.set()
                        await ws.send(
                            json.dumps(
                                {
                                    "action": "tts_playback_stopped",
                                    "response_id": response_id,
                                    "played_audio_ms": played_ms,
                                }
                            )
                        )
                elif action == "tts_finished":
                    response_id = (
                        str(data.get("response_id", ""))
                        if isinstance(data, dict)
                        else ""
                    )
                    self._tts_finished_ids.add(response_id)
                    if self._outstanding.get(response_id, 0) == 0:
                        await ws.send(
                            json.dumps(
                                {
                                    "action": "tts_playback_finished",
                                    "response_id": response_id,
                                }
                            )
                        )
                    else:
                        self._finish_pending.add(response_id)
                elif action == "error":
                    self._errors.append(str(data or payload))
        finally:
            if self._playback_task is not None:
                self._playback_task.cancel()
                await asyncio.gather(self._playback_task, return_exceptions=True)
                self._playback_task = None


def read_timeline(
    directory: Path,
    session_id: str | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    """Load the newest session JSONL timeline."""
    exact = directory / f"{session_id}.jsonl" if session_id else None
    if exact is not None:
        paths = [exact] if exact.is_file() else []
    else:
        paths = list(directory.glob("*.jsonl"))
    if not paths:
        return None, []
    path = max(paths, key=lambda item: item.stat().st_mtime_ns)
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed timeline row in {path}") from exc
    return path, records


def summarize_timeline(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract protocol, lifecycle and latency evidence from JSONL."""
    records = sorted(records, key=lambda r: float(r.get("monotonic_timestamp") or 0))
    parsed = [r for r in records if r.get("event_type") == "duplex.protocol_parsed"]
    errors = [r for r in records if r.get("event_type") == "duplex.protocol_error"]
    tokens = [r.get("state_token", "") for r in parsed if r.get("state_token")]
    counts: dict[str, int] = {}
    for record in records:
        key = str(record.get("event_type", ""))
        counts[key] = counts.get(key, 0) + 1

    def first(event_type: str) -> float | None:
        values = [float(r["monotonic_timestamp"]) for r in records if r.get("event_type") == event_type and r.get("monotonic_timestamp") is not None]
        return min(values) if values else None

    anchors = {
        "llm_first_chunk": first("llm.first_chunk"),
        "tts_started": first("tts.started"),
        "response_update": first("response.update"),
        "tts_stopped": first("tts.stopped"),
        "interruption_token": next((float(r["monotonic_timestamp"]) for r in parsed if r.get("state_token") == "<|user interruption|>"), None),
    }
    latencies = {}
    response_latencies = []
    for start in records:
        if start.get("event_type") != "tts.started" or not start.get("response_id"):
            continue
        rid, request_id = start["response_id"], start.get("request_id")
        # Some publishers carry the request only on the response start event.
        if not request_id:
            ids = {r.get("request_id") for r in records
                   if r.get("response_id") == rid and r.get("request_id")}
            request_id = next(iter(ids)) if len(ids) == 1 else None
        chunks = [r["monotonic_timestamp"] for r in records
                  if request_id and r.get("request_id") == request_id
                  and r.get("event_type") == "llm.first_chunk"]
        updates = [r["monotonic_timestamp"] for r in records
                   if r.get("response_id") == rid and r.get("event_type") == "response.update"]
        requests = [r["monotonic_timestamp"] for r in records
                    if request_id and r.get("request_id") == request_id
                    and r.get("event_type") == "duplex.micro_turn_ready"]
        pcm = [r["monotonic_timestamp"] for r in records
               if r.get("response_id") == rid and r.get("event_type") == "tts.chunk_ready"]
        response_latencies.append({
            "response_id": rid, "request_id": request_id,
            "request_to_first_token_seconds": min(chunks) - min(requests) if chunks and requests else None,
            "tts_started_to_first_chunk_seconds": min(pcm) - start["monotonic_timestamp"] if pcm else None,
            "llm_to_tts_started_seconds": start["monotonic_timestamp"] - min(chunks) if chunks else None,
            "tts_to_first_played_text_seconds": min(updates) - start["monotonic_timestamp"] if updates else None,
        })
    if response_latencies:
        for key in ("llm_to_tts_started_seconds", "tts_to_first_played_text_seconds"):
            latencies[key] = response_latencies[0][key]
    # ProtocolParsed is published after the stop action; it is not token arrival.
    stop_delays = []
    for request in records:
        if request.get("event_type") != "turn.tts_stop_requested":
            continue
        stops = [r for r in records if r.get("event_type") == "tts.stopped"
                 and r.get("response_id") == request.get("response_id")
                 and r["monotonic_timestamp"] >= request["monotonic_timestamp"]]
        if stops:
            stop_delays.append(min(r["monotonic_timestamp"] for r in stops) - request["monotonic_timestamp"])
    latencies["stop_request_to_tts_stopped_seconds"] = stop_delays
    raw = [r.get("raw_output", "") for r in parsed]
    interruption_events = [
        {
            "response_id": str(record.get("response_id") or ""),
            "reason": str(record.get("reason") or ""),
            "raw_output": str(record.get("raw_output") or ""),
            "monotonic_timestamp": record.get("monotonic_timestamp"),
        }
        for record in parsed
        if record.get("state_token") == "<|user interruption|>"
    ]
    stopped_response_ids = sorted(
        {
            str(record.get("response_id"))
            for record in records
            if record.get("event_type") == "tts.stopped"
            and record.get("response_id")
        }
    )
    interruption_stop_response_ids = sorted(
        {
            str(record.get("response_id"))
            for record in records
            if record.get("event_type") == "turn.tts_stop_requested"
            and record.get("response_id")
            and record.get("reason") in INTERRUPTION_STOP_REASONS
        }
    )
    teardown_stop_response_ids = sorted(
        {
            str(record.get("response_id"))
            for record in records
            if record.get("event_type") == "turn.tts_stop_requested"
            and record.get("response_id")
            and record.get("reason") in TEARDOWN_STOP_REASONS
        }
    )
    played: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("event_type") == "response.update":
            played.setdefault(str(record.get("response_id") or ""), []).append(
                {
                    "monotonic_timestamp": record.get("monotonic_timestamp"),
                    "text": str(record.get("text") or ""),
                }
            )
    played_text = {
        response_id: [entry["text"] for entry in entries]
        for response_id, entries in played.items()
    }
    played_text_monotonic = all(
        entries[index + 1].startswith(entries[index])
        for entries in played_text.values()
        for index in range(len(entries) - 1)
    )
    unplayed_tail_excluded = True
    for record in records:
        if record.get("event_type") != "response.finish":
            continue
        final_text = str(record.get("text") or "")
        chain = played_text.get(str(record.get("response_id") or ""))
        if not chain:
            unplayed_tail_excluded = unplayed_tail_excluded and not final_text
        elif not chain[-1].startswith(final_text):
            unplayed_tail_excluded = False
    playback_starts = [
        float(record["monotonic_timestamp"])
        for record in records
        if record.get("event_type") == "tts.started"
        and record.get("monotonic_timestamp") is not None
    ]
    playback_ends = [
        float(record["monotonic_timestamp"])
        for record in records
        if record.get("event_type") in {"response.finish", "tts.stopped", "tts.playback_finished"}
        and record.get("monotonic_timestamp") is not None
    ]
    if playback_starts:
        window_start = min(playback_starts)
        observed = [
            float(record["monotonic_timestamp"])
            for record in records
            if record.get("monotonic_timestamp") is not None
        ]
        window_end = max(playback_ends) if playback_ends else max(observed, default=window_start)
    else:
        window_start = None
        window_end = None
    asr_updates_during_playback = (
        sum(
            1
            for record in records
            if record.get("event_type") in {"asr.result_partial", "asr.result_final"}
            and record.get("monotonic_timestamp") is not None
            and window_start <= float(record["monotonic_timestamp"]) <= window_end
        )
        if window_start is not None
        else 0
    )
    serialized = [json.dumps(record, ensure_ascii=False).lower() for record in records]
    return {
        "records": len(records),
        "protocol_tokens": tokens,
        "raw_outputs": raw,
        "protocol_errors": [r.get("error_code", "") for r in errors],
        "event_counts": counts,
        "response_ids": sorted({str(r.get("response_id")) for r in records if r.get("response_id")}),
        "latencies": latencies,
        "response_latencies": response_latencies,
        "interruption_events": interruption_events,
        "stopped_response_ids": stopped_response_ids,
        "interruption_stop_response_ids": interruption_stop_response_ids,
        "teardown_stop_response_ids": teardown_stop_response_ids,
        "played_text": played_text,
        "played_text_monotonic": played_text_monotonic,
        "unplayed_tail_excluded": unplayed_tail_excluded,
        "asr_updates_during_playback": asr_updates_during_playback,
        "playback_window": [window_start, window_end] if window_start is not None else None,
        "system_backchannel_seen": any("system backchannel" in value for value in serialized),
        "direct_audio_seen": any("direct_audio" in value for value in serialized),
    }


def classify(scenario: str, report: dict[str, Any], timeline: dict[str, Any], require_interruption: bool) -> str:
    """Return PASS, FAIL or INCONCLUSIVE without guessing absent model semantics."""
    if report.get("errors") or timeline.get("protocol_errors") or timeline.get("system_backchannel_seen") or timeline.get("direct_audio_seen"):
        return "FAIL"
    if not timeline.get("played_text_monotonic", True) or not timeline.get("unplayed_tail_excluded", True):
        return "FAIL"
    counts = timeline.get("event_counts", {})
    if scenario == "interruption":
        interrupted_response_id = str(report.get("interrupted_response_id") or "")
        has_token = any(
            event["response_id"] == interrupted_response_id
            and event["reason"] == "interruption"
            and "<|user interruption|>" in event["raw_output"]
            for event in timeline.get("interruption_events", [])
        )
        stopped_same_response = (
            interrupted_response_id in timeline.get("interruption_stop_response_ids", [])
        )
        if (
            has_token
            and stopped_same_response
            and report.get("interrupted_audio_frozen")
            and report.get("tts_audio_bytes", 0)
            and report.get("status") == "COMPLETE"
        ):
            return "PASS"
        if any(e["response_id"] == interrupted_response_id for e in timeline.get("interruption_events", [])):
            return "FAIL"
        return "FAIL" if require_interruption else "INCONCLUSIVE"
    if (
        report.get("status") != "COMPLETE"
        or report.get("tts_audio_bytes", 0) <= 0
        or counts.get("tts.started", 0) <= 0
        or counts.get("response.update", 0) <= 0
    ):
        return "FAIL"
    if scenario == "long_session":
        if counts.get("duplex.micro_turn_ready", 0) < len(report.get("rounds", [])):
            return "FAIL"
    return "PASS"


def parse_scenario_audio(entries: list[str] | None) -> dict[str, list[Path]]:
    """Parse ``NAME=PATH[,PATH...]`` overrides into a scenario audio mapping."""
    mapping: dict[str, list[Path]] = {}
    for entry in entries or []:
        name, separator, value = entry.partition("=")
        if not separator or not name.strip():
            raise ValueError(f"scenario audio must be NAME=PATH: {entry}")
        paths = [
            Path(item).expanduser().resolve()
            for item in value.split(",")
            if item.strip()
        ]
        if not paths:
            raise ValueError(f"scenario audio has no path: {entry}")
        mapping[name.strip()] = paths
    return mapping


def scenario_audio_paths(
    scenario: str,
    mapping: dict[str, list[Path]],
    default: Path,
) -> list[Path]:
    """Return the request audio paths for one scenario, falling back to default."""
    return list(mapping.get(scenario) or [default])


def serve_config(config_path: Path, out: Path, model_url: str, native: bool = False) -> dict[str, Any]:
    """Prepare an isolated runtime config for the child X-Talk process."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    service_config = config.setdefault("service_config", {})
    service_config.update({"duplex_enabled": not native, "duplex_timeline_enabled": True, "duplex_timeline_dir": str(out / "timelines"), "duplex_model_url": model_url})
    return config


def normalize_wav_duration(path: Path, duration_seconds: float) -> None:
    """Trim or pad one mono PCM WAV to the FDB input duration."""
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if channels != 1 or width != 2:
        raise ValueError(f"expected mono PCM16 output WAV: {path}")
    target_bytes = max(0, round(duration_seconds * rate)) * width
    frames = frames[:target_bytes].ljust(target_bytes, b"\x00")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(frames)


def summarize_client_responses(report: dict[str, Any], sample: Path) -> dict[str, Any]:
    """Measure each response in the client's input-relative clock."""
    origin = report.get("input_start_seconds", 0.0)
    duration = report["input_audio_seconds"]
    responses: dict[str, dict[str, Any]] = {}
    for event in report.get("events", []):
        data = event.get("data")
        rid = data.get("response_id") if isinstance(data, dict) else None
        if not rid or event.get("action") not in {"start_tts", "stop_tts", "pcm_received", "playback_started"}:
            continue
        row = responses.setdefault(rid, {"response_id": rid})
        row.setdefault(event["action"] + "_seconds", event["seconds"] - origin)
    anchors = {}
    for filename, fields in (("turn_taking.json", (("turn_taking", 0),)),
                             ("interrupt.json", (("interruption_start", 0), ("interruption_end", 1)))):
        path = sample / filename
        if path.exists():
            annotations = json.loads(path.read_text())
            if annotations:
                for name, index in fields:
                    anchors[name] = float(annotations[0]["timestamp"][index])
    for row in responses.values():
        row["played_audio_bytes"] = report.get("played_audio_by_response", {}).get(row["response_id"], 0)
        played = row.get("playback_started_seconds")
        row["playback_started_in_tail"] = played is not None and played >= duration
    metrics = {}
    for name in ("turn_taking", "interruption_end"):
        if name not in anchors:
            continue
        anchor = anchors[name]
        # A response that opened before the anchor is the old answer, even if
        # its first PCM arrived after the user's interruption ended.
        candidates = [r for r in responses.values() if r.get("start_tts_seconds", -1) >= anchor]
        answer = min(candidates, key=lambda r: r["start_tts_seconds"]) if candidates else None
        metrics[name] = {"anchor_seconds": anchor,
                         "response_id": answer["response_id"] if answer else None}
        for action in ("pcm_received", "playback_started"):
            value = answer.get(action + "_seconds") if answer else None
            metrics[name]["to_" + action + "_seconds"] = value - anchor if value is not None else None
    if "interruption_start" in anchors:
        anchor = anchors["interruption_start"]
        old = [r for r in responses.values() if r.get("start_tts_seconds", float("inf")) < anchor
               and r.get("stop_tts_seconds", float("inf")) >= anchor]
        metrics["interruption_stop"] = [
            {"response_id": r["response_id"], "seconds": r["stop_tts_seconds"] - anchor}
            for r in old if "stop_tts_seconds" in r]
    return {"responses": list(responses.values()), "anchors": anchors, "latencies": metrics,
            "no_played_audio": not bool(report.get("tts_audio_bytes")),
            "aligned_first_word_seconds": None,
            "note": "PCM and playback onset are not aligned speech onset; run official alignment separately."}


def copy_fdb_sample(source: Path, destination: Path) -> None:
    """Copy FDB inputs and annotations while leaving generated outputs fresh."""
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if not path.is_file():
            continue
        if path.name in {
            "output.wav",
            "output.json",
            "clean_output.wav",
            "clean_output.json",
        }:
            continue
        target = destination / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)


async def run_fdb_batch(args: argparse.Namespace) -> dict[str, Any]:
    """Generate time-aligned FDB audio outputs with one new session per sample."""
    args.out.mkdir(parents=True, exist_ok=False)
    if args.fdb_output_root == args.fdb_input_root or args.fdb_input_root in args.fdb_output_root.parents:
        raise ValueError("FDB output must be outside the input tree")
    args.fdb_output_root.mkdir(parents=True, exist_ok=False)
    config = serve_config(args.config, args.out, args.model_url, args.native)
    inputs = [
        path
        for path in sorted(args.fdb_input_root.rglob("*input.wav"))
        if path.name in {"input.wav", "clean_input.wav"}
    ]
    sample_dirs = sorted({path.parent for path in inputs})
    if args.fdb_limit > 0:
        sample_dirs = sample_dirs[: args.fdb_limit]
    inputs = [path for path in inputs if path.parent in sample_dirs]
    if not inputs:
        raise ValueError(f"no FDB input WAV files found under {args.fdb_input_root}")
    port = _pick_free_port()
    context = multiprocessing.get_context("spawn")
    os.environ["XTALK_SERVE_LOG"] = str(args.out / "xtalk_serve.log")
    server = context.Process(target=_serve, args=(config, "127.0.0.1", port))
    server.start()
    results: list[dict[str, Any]] = []
    try:
        await _wait_for_server(server, port, time.monotonic() + args.server_timeout)
        for index, input_path in enumerate(inputs):
            relative = input_path.relative_to(args.fdb_input_root)
            sample_output = args.fdb_output_root / relative.parent
            copy_fdb_sample(input_path.parent, sample_output)
            output_name = input_path.name.replace("input.wav", "output.wav")
            output_path = sample_output / output_name
            client = A4ReplayClient(
                f"http://127.0.0.1:{port}",
                f"ws://127.0.0.1:{port}/ws",
                args.timeout,
                output_path,
                fdb_tail_seconds=args.fdb_tail_seconds,
                fdb_tail_audio=getattr(args, 'fdb_tail_audio', False),
            )
            pcm = _load_pcm16(input_path)
            report = await client.run(pcm, 1, scenario="fdb")
            duration = len(pcm) / (2 * SAMPLE_RATE)
            diagnostic_path = args.out / "diagnostics" / relative.parent / output_name
            diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output_path, diagnostic_path)
            normalize_wav_duration(output_path, duration)
            await asyncio.sleep(0.5)
            timeline_path, records = read_timeline(
                Path(config["service_config"]["duplex_timeline_dir"]),
                client.session_id,
            )
            timeline = summarize_timeline(records)
            failed = bool(
                report.get("errors")
                or timeline["protocol_errors"]
                or timeline["system_backchannel_seen"]
                or timeline["direct_audio_seen"]
                or not records
                or report.get("status") != "COMPLETE"
            )
            result = {
                **report,
                "status": "FAIL" if failed else "PASS",
                "input": str(input_path),
                "output": str(output_path),
                "sample_index": index,
                "transport_status": "FAIL" if failed else "PASS",
                "semantic_status": "PENDING_OFFICIAL_SCORING",
                "diagnostic_output": str(diagnostic_path),
                "client_measurements": summarize_client_responses(report, input_path.parent),
                "timeline_path": str(timeline_path) if timeline_path else None,
                "timeline": timeline,
            }
            report_name = (
                "clean_a4_report.json"
                if input_path.name.startswith("clean_")
                else "a4_report.json"
            )
            (sample_output / report_name).write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            results.append(result)
    finally:
        server.terminate()
        server.join(timeout=10)
        if server.is_alive():
            server.kill()
    summary = {
        "status": "PASS" if results and all(r["status"] == "PASS" for r in results) else "FAIL",
        "input_root": str(args.fdb_input_root),
        "output_root": str(args.fdb_output_root),
        "samples": results,
        "note": "Inference audio only; run official FDB ASR alignment and scoring separately.",
    }
    (args.out / "fdb_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run all selected scenarios against one X-Talk process."""
    args.out.mkdir(parents=True, exist_ok=False)
    config = serve_config(args.config, args.out, args.model_url, args.native)
    port = _pick_free_port()
    context = multiprocessing.get_context("spawn")
    os.environ["XTALK_SERVE_LOG"] = str(args.out / "xtalk_serve.log")
    server = context.Process(target=_serve, args=(config, "127.0.0.1", port))
    server.start()
    results = []
    try:
        await _wait_for_server(server, port, time.monotonic() + args.server_timeout)
        for scenario in args.scenarios:
            scenario_out = args.out / scenario
            scenario_out.mkdir(parents=True, exist_ok=True)
            if scenario == "interruption" and not args.interruption_audio.is_file():
                results.append({"scenario": scenario, "status": "BLOCKED", "reason": "missing interruption audio"})
                continue
            inputs = scenario_audio_paths(scenario, args.scenario_audio, args.audio)
            missing = [path for path in inputs if not path.is_file()]
            if missing or (scenario == "pause" and len(inputs) != 2):
                results.append(
                    {
                        "scenario": scenario,
                        "status": "BLOCKED",
                        "reason": f"missing or malformed scenario audio: {[str(path) for path in missing]}",
                    }
                )
                continue
            client = A4ReplayClient(f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}/ws", args.timeout, scenario_out / "output.wav")
            pcm = _load_pcm16(inputs[0])
            if scenario == "interruption":
                report = await client.run(
                    pcm,
                    1,
                    scenario=scenario,
                    barge_pcm=_load_pcm16(args.interruption_audio),
                    barge_after_seconds=args.barge_after_seconds,
                )
            elif scenario == "long_session":
                report = await client.run(
                    pcm,
                    args.rounds,
                    scenario=scenario,
                )
            elif scenario == "pause":
                report = await client.run(
                    pcm,
                    1,
                    scenario=scenario,
                    pause_pcm=_load_pcm16(inputs[1]),
                    pause_gap_seconds=args.pause_gap_seconds,
                )
            else:
                report = await client.run(pcm, 1, scenario=scenario)
            await asyncio.sleep(0.2)
            timeline_path, records = read_timeline(
                Path(config["service_config"]["duplex_timeline_dir"]),
                client.session_id,
            )
            timeline = summarize_timeline(records)
            result = {**report, "scenario": scenario, "status": classify(scenario, report, timeline, args.require_interruption), "timeline_path": str(timeline_path) if timeline_path else None, "timeline": timeline}
            (scenario_out / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append(result)
    finally:
        server.terminate()
        server.join(timeout=10)
        if server.is_alive():
            server.kill()
    status = "FAIL" if any(r.get("status") == "FAIL" for r in results) else ("PASS" if results and all(r.get("status") == "PASS" for r in results) else "INCONCLUSIVE")
    summary = {"status": status, "scenarios": results, "config": str(args.config), "model_url": args.model_url}
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    """Run selected A4 scenarios and return a CI-style exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-url", default="http://127.0.0.1:8006")
    parser.add_argument("--interruption-audio", type=Path)
    parser.add_argument(
        "--scenario-audio",
        action="append",
        metavar="NAME=PATH[,PATH...]",
        help="per-scenario request audio; pause takes two comma-separated paths",
    )
    parser.add_argument("--scenario", dest="scenarios", action="append", choices=SCENARIOS)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--server-timeout", type=float, default=60.0)
    parser.add_argument("--barge-after-seconds", type=float, default=2.0)
    parser.add_argument("--pause-gap-seconds", type=float, default=1.5)
    parser.add_argument("--require-interruption", action="store_true")
    parser.add_argument("--fdb-input-root", type=Path)
    parser.add_argument("--fdb-output-root", type=Path)
    parser.add_argument("--fdb-limit", type=int, default=5)
    parser.add_argument("--fdb-tail-seconds", type=float, default=5.0)
    parser.add_argument("--native", action="store_true", help="keep native semantic managers for FDB comparison")
    args = parser.parse_args()
    if not 0 <= args.fdb_tail_seconds <= 60:
        parser.error("--fdb-tail-seconds must be between 0 and 60")
    if args.native and args.fdb_input_root is None:
        parser.error("--native is supported only in FDB mode")
    args.config = args.config.resolve()
    args.out = args.out.resolve()
    if args.fdb_input_root is not None:
        if args.fdb_output_root is None:
            parser.error("--fdb-input-root requires --fdb-output-root")
        args.fdb_input_root = args.fdb_input_root.resolve()
        args.fdb_output_root = args.fdb_output_root.resolve()
        summary = asyncio.run(run_fdb_batch(args))
    else:
        args.scenario_audio = parse_scenario_audio(args.scenario_audio)
        args.scenarios = args.scenarios or list(SCENARIOS)
        default_audio = args.audio.resolve() if args.audio is not None else None
        without_override = [
            scenario
            for scenario in args.scenarios
            if scenario not in args.scenario_audio
        ]
        if default_audio is None and without_override:
            parser.error(
                f"--audio is required for scenarios without overrides: {without_override}"
            )
        if default_audio is not None and not default_audio.is_file():
            parser.error(f"missing input WAV: {default_audio}")
        args.audio = default_audio or Path("/__missing_default_audio__")
        args.interruption_audio = (
            args.interruption_audio.resolve()
            if args.interruption_audio is not None
            else Path("/__missing_interruption_audio__")
        )
        summary = asyncio.run(run(args))
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if summary["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
