"""Headless full-duplex client for the official DuplexCascade server (P1.2).

The client speaks exactly the browser protocol of the unmodified official
``server.py``:

- outbound: binary little-endian float32 PCM frames (80 ms @ 24 kHz) and the
  text control messages ``Reset`` / ``Done``;
- inbound: JSON ``user_asr`` / ``assistant_text`` / ``assistant_special`` /
  ``audio_control`` messages and binary TTS PCM frames.

It replaces the browser tab: a scripted scenario feeds the microphone stream,
every TTS frame is handed to the single playback owner, and the P1.2
acceptance evidence is recorded as structured events:

- ``audio_chunk_sent`` -- microphone frames keep flowing *while the system is
  speaking* (``frames_sent_while_speaking`` in the result proves the link is
  duplex, not push-to-talk);
- ``user_barge_in`` -- a scripted barge-in segment started while the owner was
  still playing (records the playhead position, i.e. the interruption point);
- ``playback_stop_command`` / ``playback_stopped`` -- the server-side
  ``audio_control: stop`` and the cancelled-unplayed-samples outcome;
- ``micro_turn_decision`` / ``answer_phase`` / ``backchannel`` -- the official
  control tokens as they arrive.

Timing model: the harness is a real-time system, so all client scheduling and
timeouts (segment start, send pacing, idle wait) use wall time in every clock
mode.  The configured clock paces only the playback owner (see
:mod:`interclarify.realtime.clock`).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import websockets

from .playback import PlaybackSink
from .scenarios import Scenario, materialize_segment

# Assistant control tokens emitted by the official server (server.py).
_FINISH_TALKING = "<|user finish talking|>"
_BACKCHANNEL = "<|user backchannel|>"
_THINKING = "<|user is thinking|>"
_INTERRUPTION = "<|user interruption|>"
_USER_TALKING = "<|user is talking|>"


@dataclass
class SessionResult:
    """Aggregate evidence collected for one scripted scenario."""

    scenario: str
    control_sequence: List[str] = field(default_factory=list)
    asr_texts: List[str] = field(default_factory=list)
    assistant_text: str = ""
    backchannel_count: int = 0
    answer_phase_count: int = 0
    server_barge_in_count: int = 0
    barge_in_count: int = 0
    frames_sent: int = 0
    frames_sent_while_speaking: int = 0
    tts_received_samples: int = 0
    tts_played_samples: int = 0
    tts_cancelled_samples: int = 0
    playback_max_backlog_samples: int = 0
    send_underruns: int = 0
    max_send_gap_ms: float = 0.0
    duration_s: float = 0.0

    def last_asr_text(self) -> str:
        return self.asr_texts[-1] if self.asr_texts else ""


@dataclass
class _SessionState:
    """Mutable per-scenario accumulator (single recv task writes it)."""

    control_sequence: List[str] = field(default_factory=list)
    asr_texts: List[str] = field(default_factory=list)
    assistant_text: str = ""
    backchannel_count: int = 0
    answer_phase_count: int = 0
    server_barge_in_count: int = 0
    tts_received_samples: int = 0
    last_tts_recv_monotonic: float = 0.0
    recv_messages: int = 0


class DuplexSessionClient:
    """Scripted duplex session against one official server connection."""

    def __init__(
        self,
        *,
        url: str,
        playback: PlaybackSink,
        emit,
        sample_rate: int = 24000,
        frame_samples: int = 1920,
        connect_timeout_s: float = 10.0,
        post_audio_timeout_s: float = 30.0,
        idle_gap_s: float = 2.0,
        no_tts_grace_s: float = 8.0,
        send_pace_budget_ms: float = 120.0,
        poll_interval_s: float = 0.02,
        chunk_event_stride: int = 1,
    ) -> None:
        self.url = url
        self.playback = playback
        self._emit = emit
        self.sample_rate = int(sample_rate)
        self.frame_samples = int(frame_samples)
        self.frame_seconds = self.frame_samples / float(self.sample_rate)
        self.connect_timeout_s = float(connect_timeout_s)
        self.post_audio_timeout_s = float(post_audio_timeout_s)
        self.idle_gap_s = float(idle_gap_s)
        self.no_tts_grace_s = float(no_tts_grace_s)
        self.send_pace_budget_ms = float(send_pace_budget_ms)
        self.poll_interval_s = float(poll_interval_s)
        self.chunk_event_stride = max(1, int(chunk_event_stride))
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._state = _SessionState()

    # -- connection lifecycle -------------------------------------------------
    async def connect(self) -> None:
        """Open the WebSocket connection and start the receive loop."""
        if self._ws is not None:
            raise RuntimeError("client is already connected")
        self._ws = await websockets.connect(self.url, max_size=8 << 20, open_timeout=self.connect_timeout_s)
        self._state = _SessionState()
        self._recv_task = asyncio.create_task(self._recv_loop(self._ws))
        self._emit("session_connected", url=self.url)

    async def close(self) -> None:
        """Send ``Done``, drain the receive loop and disconnect."""
        if self._ws is None:
            return
        try:
            await self._ws.send("Done")
        except Exception:
            pass
        if self._recv_task is not None:
            try:
                await asyncio.wait_for(self._recv_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._recv_task.cancel()
            self._recv_task = None
        try:
            await self._ws.close()
        except Exception:
            pass
        self._ws = None
        self._emit("session_closed", url=self.url)

    async def send_reset(self, settle_seconds: float = 1.0) -> None:
        """Restart the server-side session (text ``Reset``) and let it settle.

        The official server tears down the session tasks, reconnects its STT
        socket and drains queued audio before the next session starts; sending
        new audio too early would land in the drain window and be dropped.
        """
        if self._ws is None:
            raise RuntimeError("client is not connected")
        await self._ws.send("Reset")
        self._emit("session_reset", settle_seconds=settle_seconds)
        await asyncio.sleep(max(0.0, settle_seconds))

    # -- scenario execution -------------------------------------------------
    async def run(self, scenario: Scenario) -> SessionResult:
        """Connect, run one scenario and disconnect (single-scenario helper)."""
        await self.connect()
        try:
            return await self.run_scenario(scenario)
        finally:
            await self.close()

    async def run_scenario(self, scenario: Scenario) -> SessionResult:
        """Play one scripted scenario over the current connection."""
        if self._ws is None:
            raise RuntimeError("client is not connected")
        self._state = _SessionState()
        state = self._state
        start = time.monotonic()
        send_stats = {"frames": 0, "while_speaking": 0, "underruns": 0, "max_gap_ms": 0.0}
        prev_send: Optional[float] = None
        barge_in_marked: set[str] = set()
        # Pre-materialize all segment audio so disk I/O never interrupts the
        # real-time microphone stream between segments.
        materialized = [(segment, materialize_segment(segment, self.sample_rate)) for segment in scenario.segments]

        for index, (segment, pcm) in enumerate(materialized):
            await self._wait_for_schedule(segment, start)
            frame_starts = time.monotonic()
            for offset in range(0, pcm.size, self.frame_samples):
                frame = pcm[offset : offset + self.frame_samples]
                # Pace the microphone stream at real time regardless of clock mode.
                target = frame_starts + offset / float(self.sample_rate)
                delay = target - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                now = time.monotonic()
                if prev_send is not None:
                    gap_ms = (now - prev_send) * 1000.0
                    send_stats["max_gap_ms"] = max(send_stats["max_gap_ms"], gap_ms)
                    if gap_ms > self.send_pace_budget_ms:
                        send_stats["underruns"] += 1
                        self._emit(
                            "send_underrun",
                            scenario=scenario.name,
                            segment=segment.label,
                            gap_ms=round(gap_ms, 3),
                            budget_ms=self.send_pace_budget_ms,
                        )
                speaking = self.playback.is_speaking()
                if speaking:
                    send_stats["while_speaking"] += 1
                if (
                    segment.label not in barge_in_marked
                    and speaking
                    and segment.label in ("barge_in", "interruption")
                ):
                    barge_in_marked.add(segment.label)
                    self._emit(
                        "user_barge_in",
                        scenario=scenario.name,
                        segment=segment.label,
                        segment_index=index,
                        playback_played_samples=self.playback.played_samples,
                        playback_pending_samples=self.playback.pending_samples,
                    )
                await self._ws.send(np.asarray(frame, dtype="<f4").tobytes())
                prev_send = time.monotonic()
                send_stats["frames"] += 1
                if send_stats["frames"] % self.chunk_event_stride == 0 or offset + self.frame_samples >= pcm.size:
                    self._emit(
                        "audio_chunk_sent",
                        scenario=scenario.name,
                        segment=segment.label,
                        segment_index=index,
                        frame=send_stats["frames"],
                        samples=int(frame.size),
                        playback_speaking=speaking,
                    )
            self._emit(
                "segment_sent",
                scenario=scenario.name,
                segment=segment.label,
                segment_index=index,
                frames=send_stats["frames"],
            )

        self._emit("scenario_audio_sent", scenario=scenario.name, frames=send_stats["frames"])
        await self._wait_until_idle(state, audio_sent_at=time.monotonic())

        result = SessionResult(
            scenario=scenario.name,
            control_sequence=list(state.control_sequence),
            asr_texts=list(state.asr_texts),
            assistant_text=state.assistant_text,
            backchannel_count=state.backchannel_count,
            answer_phase_count=state.answer_phase_count,
            server_barge_in_count=state.server_barge_in_count,
            barge_in_count=len(barge_in_marked),
            frames_sent=send_stats["frames"],
            frames_sent_while_speaking=send_stats["while_speaking"],
            tts_received_samples=state.tts_received_samples,
            tts_played_samples=self.playback.played_samples,
            tts_cancelled_samples=self.playback.cancelled_samples,
            playback_max_backlog_samples=self.playback.max_backlog_samples,
            send_underruns=send_stats["underruns"],
            max_send_gap_ms=round(send_stats["max_gap_ms"], 3),
            duration_s=round(time.monotonic() - start, 3),
        )
        self._emit("scenario_end", scenario=scenario.name, duration_s=result.duration_s)
        return result

    # -- scheduling -------------------------------------------------------------
    async def _wait_for_schedule(self, segment, scenario_start: float) -> None:
        deadline = scenario_start + segment.start_seconds
        delay = deadline - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        if segment.start_condition:
            # Wait until the playback owner has played enough TTS audio (e.g.
            # land a scripted barge-in mid-answer).  If playback stalls below
            # the threshold (answer cancelled, model stayed silent), time out
            # and send anyway -- the scenario expectations judge the outcome.
            min_played = float(segment.start_condition.get("tts_played_min_seconds", 0.0))
            deadline = time.monotonic() + self.post_audio_timeout_s
            while self.playback.played_seconds() < min_played:
                if self._ws is None or self._ws.closed:
                    raise ConnectionError("connection closed while waiting for tts_played_min_seconds")
                if time.monotonic() >= deadline:
                    self._emit(
                        "start_condition_timeout",
                        segment=segment.label,
                        tts_played_seconds=round(self.playback.played_seconds(), 3),
                        required_seconds=min_played,
                    )
                    return
                await asyncio.sleep(self.poll_interval_s)

    async def _wait_until_idle(self, state: _SessionState, audio_sent_at: float) -> None:
        # When no TTS has arrived yet, the model may still be deciding its
        # first answer; wait out a dedicated grace period instead of the
        # (shorter) inter-chunk idle gap.
        deadline = time.monotonic() + self.post_audio_timeout_s
        while True:
            now = time.monotonic()
            silent_for = now - state.last_tts_recv_monotonic if state.last_tts_recv_monotonic else 0.0
            if state.tts_received_samples > 0:
                quiet = silent_for >= self.idle_gap_s
            else:
                quiet = now - audio_sent_at >= self.no_tts_grace_s
            if quiet and not self.playback.is_speaking():
                self._emit(
                    "session_idle",
                    silent_for_s=round(silent_for, 3),
                    no_tts=state.tts_received_samples == 0,
                )
                return
            if self._recv_task is not None and self._recv_task.done() and not self.playback.is_speaking():
                # The receiver ended mid-scenario (server closed or crashed):
                # report immediately instead of spinning until the timeout.
                self._emit(
                    "session_recv_ended",
                    tts_received_samples=state.tts_received_samples,
                    recv_error=(self._recv_task.exception() is not None),
                )
                return
            if now >= deadline:
                self._emit(
                    "session_timeout",
                    post_audio_timeout_s=self.post_audio_timeout_s,
                    tts_received_samples=state.tts_received_samples,
                    playback_pending_samples=self.playback.pending_samples,
                )
                return
            await asyncio.sleep(self.poll_interval_s)

    # -- receive loop ---------------------------------------------------------
    async def _recv_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        try:
            async for raw in ws:
                # Always read the current scenario state: run_scenario swaps it per
                # scenario while the receive task lives for the whole connection.
                state = self._state
                if isinstance(raw, (bytes, bytearray)):
                    pcm = np.frombuffer(bytes(raw), dtype="<f4")
                    state.tts_received_samples += int(pcm.size)
                    state.last_tts_recv_monotonic = time.monotonic()
                    self.playback.commit(pcm)
                    self._emit(
                        "tts_audio_received",
                        samples=int(pcm.size),
                        tts_received_samples=state.tts_received_samples,
                        playback_pending_samples=self.playback.pending_samples,
                    )
                    continue
                try:
                    message: Dict[str, Any] = json.loads(raw)
                except (ValueError, TypeError):
                    self._emit("server_message_unparsed", raw=str(raw)[:200])
                    continue
                state.recv_messages += 1
                mtype = message.get("type")
                if mtype == "user_asr":
                    text = str(message.get("text", ""))
                    if not text:
                        continue  # UI clear marker sent by the server on Reset
                    state.asr_texts.append(text)
                    self._emit("asr_partial", text=text)
                elif mtype == "assistant_text":
                    text = str(message.get("text", ""))
                    state.assistant_text += text
                    self._emit("assistant_text", text=text)
                elif mtype == "assistant_special":
                    self._on_special(str(message.get("text", "")), state)
                elif mtype == "audio_control":
                    action = str(message.get("action", ""))
                    reason = str(message.get("reason", ""))
                    cancelled = 0
                    if action == "stop":
                        cancelled = self.playback.stop(reason=reason)
                    self._emit("playback_stop_command", action=action, reason=reason, cancelled_samples=cancelled)
                else:
                    self._emit("server_message", raw=message)
        except websockets.exceptions.ConnectionClosed:
            return
        except Exception as exc:  # unexpected receiver death: record and surface to waiters
            self._emit("session_recv_error", error=repr(exc))
            raise

    def _on_special(self, text: str, state: _SessionState) -> None:
        if not text:
            return  # UI clear marker sent on Reset
        state.control_sequence.append(text)
        self._emit("micro_turn_decision", control=text)
        if text == _FINISH_TALKING:
            state.answer_phase_count += 1
            self._emit("answer_phase")
        elif text == _BACKCHANNEL:
            state.backchannel_count += 1
            self._emit("backchannel")
        elif text == _THINKING:
            self._emit("user_thinking")
        elif text in (_INTERRUPTION, _USER_TALKING):
            if self.playback.is_speaking():
                state.server_barge_in_count += 1
                self._emit(
                    "server_barge_in",
                    control=text,
                    playback_played_samples=self.playback.played_samples,
                    playback_pending_samples=self.playback.pending_samples,
                )
