"""CPU-only tests for the P1.2 real-time duplex harness.

Covers the pacing clock, the single playback owner, scenario loading and the
headless duplex client end-to-end against a stub server that speaks the
official ``server.py`` browser protocol (JSON control + binary TTS PCM).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import soundfile as sf  # noqa: E402
import websockets  # noqa: E402

from interclarify.realtime.clock import RealClock, VirtualClock, make_clock  # noqa: E402
from interclarify.realtime.client import DuplexSessionClient  # noqa: E402
from interclarify.realtime.playback import VirtualPlaybackSink  # noqa: E402
from interclarify.realtime.scenarios import (  # noqa: E402
    Scenario,
    Segment,
    load_audio_mono,
    load_scenarios,
    materialize_segment,
)
from interclarify.duplex.official_server import OfficialDuplexServer, verify_weight_sha256  # noqa: E402

SR = 24000
FRAME = 1920


# --------------------------------------------------------------------------
# clocks
# --------------------------------------------------------------------------

def test_virtual_clock_advances_without_sleeping() -> None:
    clock = VirtualClock()
    before = time.monotonic()
    clock.sleep(3600.0)
    assert time.monotonic() - before < 1.0
    assert clock.now() == pytest.approx(3600.0)
    clock.sleep_until(7200.0)
    assert clock.now() == pytest.approx(7200.0)
    clock.sleep_until(100.0)  # past deadline: no-op
    assert clock.now() == pytest.approx(7200.0)


def test_real_clock_is_monotonic() -> None:
    clock = RealClock()
    t0 = clock.now()
    clock.sleep(0.01)
    assert clock.now() > t0


def test_make_clock_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        make_clock("sidereal")
    assert isinstance(make_clock("real"), RealClock)
    assert isinstance(make_clock("virtual"), VirtualClock)


# --------------------------------------------------------------------------
# virtual playback owner
# --------------------------------------------------------------------------

def _collect_events() -> tuple[list, object]:
    events: list = []
    return events, (lambda event_type, **payload: events.append((event_type, payload)))


def test_virtual_sink_plays_head_and_cancels_tail(tmp_path: Path) -> None:
    events, emit = _collect_events()
    clock = VirtualClock()
    played_file = tmp_path / "played.f32le"
    sink = VirtualPlaybackSink(SR, clock, emit, played_path=played_file)

    sink.commit(np.ones(FRAME, dtype=np.float32))  # 80 ms
    assert sink.is_speaking()
    clock.advance(0.03)
    assert sink.played_samples == pytest.approx(int(0.03 * SR), abs=2)

    # Commit 2 more seconds, play 0.5s of them, then cancel the rest.  The
    # cancelled tail includes the 80ms first frame's unplayed remainder.
    sink.commit(np.ones(2 * SR, dtype=np.float32))
    clock.advance(0.5)
    cancelled = sink.stop(reason="barge-in")
    expected = (FRAME - int(0.03 * SR)) + (2 * SR - int(0.5 * SR))
    assert cancelled == pytest.approx(expected, abs=8)
    assert not sink.is_speaking()
    assert sink.cancelled_samples == cancelled

    played = np.frombuffer(played_file.read_bytes(), dtype="<f4")
    assert played.size == sink.played_samples
    assert played.size == pytest.approx(int(0.53 * SR), abs=8)

    kinds = [kind for kind, _ in events]
    assert "playback_started" in kinds
    assert "playback_stopped" in kinds
    stop_payload = dict(events[kinds.index("playback_stopped")][1])
    assert stop_payload["reason"] == "barge-in"
    assert stop_payload["cancelled_samples"] == cancelled
    assert "playback_finished" not in kinds  # cancelled, not drained


def test_virtual_sink_natural_drain_emits_finished(tmp_path: Path) -> None:
    events, emit = _collect_events()
    clock = VirtualClock()
    sink = VirtualPlaybackSink(SR, clock, emit)
    sink.commit(np.ones(FRAME, dtype=np.float32))
    clock.advance(FRAME / SR)
    assert not sink.is_speaking()
    kinds = [kind for kind, _ in events]
    assert "playback_finished" in kinds
    assert "playback_stopped" not in kinds


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------

def _write_wav(path: Path, seconds: float, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sf.write(str(path), 0.1 * np.sin(2 * np.pi * 440 * t), sr, subtype="FLOAT")


def _scenario_file(root: Path, audio_rel: str | None = "audio/seg.wav") -> Path:
    segment = {"label": "speech", "synth_text": "hello world", "start_seconds": 0.0}
    if audio_rel is None:
        segment["audio"] = None
        segment["duration_seconds"] = 1.0
    else:
        segment["audio"] = audio_rel
    payload = {
        "scenarios": [
            {
                "name": "demo",
                "description": "test",
                "segments": [segment],
                "expect": {"answer_expected": True, "user_asr_contains": "hello"},
            }
        ]
    }
    path = root / "scenarios.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_scenarios_and_materialize(tmp_path: Path) -> None:
    _write_wav(tmp_path / "audio" / "seg.wav", seconds=1.0)
    scenarios = load_scenarios(_scenario_file(tmp_path), tmp_path)
    assert len(scenarios) == 1
    scenario = scenarios[0]
    assert scenario.name == "demo"
    assert scenario.expect["answer_expected"] is True

    pcm = materialize_segment(scenario.segments[0], SR)
    assert pcm.size == SR
    # truncation + zero padding honour the scheduling contract
    seg = scenario.segments[0]
    short = Segment(label="x", audio=seg.audio, duration_seconds=0.5)
    assert materialize_segment(short, SR).size == SR // 2
    long = Segment(label="x", audio=seg.audio, duration_seconds=3.0)
    assert materialize_segment(long, SR).size == 3 * SR
    silence = Segment(label="s", audio=None, duration_seconds=1.25)
    assert materialize_segment(silence, SR).size == int(1.25 * SR)
    assert not materialize_segment(silence, SR).any()


def test_load_scenarios_missing_audio_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_scenarios(_scenario_file(tmp_path), tmp_path)


def test_load_scenarios_rejects_unknown_expect_key(tmp_path: Path) -> None:
    _write_wav(tmp_path / "audio" / "seg.wav", seconds=1.0)
    path = _scenario_file(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scenarios"][0]["expect"]["answers_expected"] = True  # typo
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenarios(path, tmp_path)


def test_load_audio_mono_resamples(tmp_path: Path) -> None:
    src = tmp_path / "tone16k.wav"
    _write_wav(src, seconds=1.0, sr=16000)
    pcm = load_audio_mono(src, SR)
    assert pcm.dtype == np.float32
    assert pcm.size == pytest.approx(SR, abs=32)
    assert np.abs(pcm).max() > 0.01


# --------------------------------------------------------------------------
# stub server speaking the official browser protocol
# --------------------------------------------------------------------------

def _json(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False)


class _RegularAnswerStub:
    """One ASR text, one finish-talking answer with 2s of TTS audio."""

    def __init__(self) -> None:
        self.reset_count = 0
        self.done = asyncio.Event()

    async def handle(self, ws) -> None:  # noqa: ANN001
        frames = 0
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    frames += 1
                    if frames == 5:
                        await ws.send(_json({"type": "user_asr", "text": "hello there"}))
                    elif frames == 8:
                        await ws.send(_json({"type": "assistant_special", "text": "<|user finish talking|>"}))
                        await ws.send(_json({"type": "assistant_text", "text": "hello friend"}))
                        await ws.send(np.ones(2 * SR, dtype="<f4").tobytes())
                elif msg.strip() == "Reset":
                    self.reset_count += 1
                    frames = 0
                    await ws.send(_json({"type": "user_asr", "text": ""}))
                elif msg.strip() == "Done":
                    return
        except websockets.exceptions.ConnectionClosed:
            return
        finally:
            self.done.set()


class _BargeInStub:
    """Answer with 4s of TTS; after the question segment has fully been sent
    (``question_frames``), treat further frames as a barge-in: stop playback
    and answer a new question (mirrors server.py barge-in handling)."""

    def __init__(self, question_frames: int = 13) -> None:
        self.question_frames = question_frames
        self.done = asyncio.Event()

    async def handle(self, ws) -> None:  # noqa: ANN001
        frames = 0
        speaking = False
        barged = False
        barge_frames = 0
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    frames += 1
                    if frames == 5:
                        await ws.send(_json({"type": "user_asr", "text": "tell me a story"}))
                    elif frames == 8 and not speaking:
                        speaking = True
                        await ws.send(_json({"type": "assistant_special", "text": "<|user finish talking|>"}))
                        await ws.send(_json({"type": "assistant_text", "text": "once upon a time"}))
                        await ws.send(np.ones(4 * SR, dtype="<f4").tobytes())
                    elif speaking and frames > self.question_frames and not barged:
                        barged = True
                        barge_frames = 1
                        await ws.send(_json({"type": "assistant_special", "text": "<|user interruption|>"}))
                        await ws.send(_json({"type": "audio_control", "action": "stop", "reason": "<|user interruption|>"}))
                    elif barged:
                        barge_frames += 1
                        if barge_frames == 8:
                            await ws.send(_json({"type": "user_asr", "text": "what time is it"}))
                        elif barge_frames == 12:
                            await ws.send(_json({"type": "assistant_special", "text": "<|user finish talking|>"}))
                            await ws.send(_json({"type": "assistant_text", "text": "it is noon"}))
                            await ws.send(np.ones(SR, dtype="<f4").tobytes())
                elif msg.strip() == "Done":
                    return
        except websockets.exceptions.ConnectionClosed:
            return
        finally:
            self.done.set()


@pytest.fixture
def stub_server():
    """Start a stub server; yields (url, stub instance)."""

    async def _start(handler) -> tuple[str, object]:
        server = await websockets.serve(handler.handle, "127.0.0.1", 0, max_size=8 << 20)
        port = server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}/", server

    return _start


def _speech_scenario(name: str, seconds: float, extra_segments: list | None = None) -> Scenario:
    segments = [Segment(label="speech", audio=None, duration_seconds=seconds)]
    if extra_segments:
        segments.extend(extra_segments)
    return Scenario(name=name, description=name, segments=segments, expect={})


def test_client_regular_answer(stub_server, tmp_path: Path) -> None:
    async def _run():
        stub = _RegularAnswerStub()
        url, server = await stub_server(stub)
        events, emit = _collect_events()
        playback = VirtualPlaybackSink(SR, RealClock(), emit, played_path=tmp_path / "played.f32le")
        client = DuplexSessionClient(
            url=url,
            playback=playback,
            emit=emit,
            sample_rate=SR,
            frame_samples=FRAME,
            post_audio_timeout_s=10,
            idle_gap_s=0.5,
            no_tts_grace_s=3,
        )
        # 1s speech (13 frames) + 1s silence: stub answers at frame 8.
        scenario = _speech_scenario("regular", 1.0, [Segment(label="tail", audio=None, duration_seconds=1.0)])
        result = await client.run(scenario)
        server.close()
        await server.wait_closed()
        return result, events

    result, events = asyncio.run(_run())
    assert result.control_sequence == ["<|user finish talking|>"]
    assert result.last_asr_text() == "hello there"
    assert result.assistant_text == "hello friend"
    assert result.tts_received_samples == 2 * SR
    assert result.tts_played_samples == pytest.approx(2 * SR, abs=FRAME)
    assert result.tts_cancelled_samples == 0
    assert result.frames_sent_while_speaking > 0  # duplex: tail frames sent while answering
    kinds = [kind for kind, _ in events]
    assert "tts_audio_received" in kinds
    assert "answer_phase" in kinds
    assert "playback_finished" in kinds


def test_client_barge_in_stop_and_resume(stub_server, tmp_path: Path) -> None:
    async def _run():
        stub = _BargeInStub()
        url, server = await stub_server(stub)
        events, emit = _collect_events()
        playback = VirtualPlaybackSink(SR, RealClock(), emit, played_path=tmp_path / "played.f32le")
        client = DuplexSessionClient(
            url=url,
            playback=playback,
            emit=emit,
            sample_rate=SR,
            frame_samples=FRAME,
            post_audio_timeout_s=15,
            idle_gap_s=0.5,
            no_tts_grace_s=3,
        )
        scenario = _speech_scenario(
            "barge",
            1.0,
            [
                Segment(
                    label="barge_in",
                    audio=None,
                    duration_seconds=1.2,
                    start_condition={"tts_played_min_seconds": 0.5},
                ),
                Segment(label="tail", audio=None, duration_seconds=1.0),
            ],
        )
        result = await client.run(scenario)
        server.close()
        await server.wait_closed()
        return result, events

    result, events = asyncio.run(_run())
    assert "<|user interruption|>" in result.control_sequence
    assert result.control_sequence.count("<|user finish talking|>") == 2
    assert result.barge_in_count == 1
    assert result.server_barge_in_count == 1
    assert result.tts_received_samples == 5 * SR
    # 4s committed, playback cancelled mid-way, 1s re-answer fully played.
    assert result.tts_cancelled_samples > 2 * SR
    assert result.tts_played_samples < 4 * SR
    assert result.tts_played_samples >= SR
    assert result.frames_sent_while_speaking > 0

    kinds = [kind for kind, _ in events]
    barge_payload = dict(events[kinds.index("user_barge_in")][1])
    assert barge_payload["segment"] == "barge_in"
    assert barge_payload["playback_played_samples"] >= int(0.5 * SR)
    stop_cmd = dict(events[kinds.index("playback_stop_command")][1])
    assert stop_cmd["action"] == "stop"
    assert stop_cmd["cancelled_samples"] > 0
    stopped = dict(events[kinds.index("playback_stopped")][1])
    assert stopped["reason"] == "<|user interruption|>"


def test_client_reset_between_scenarios(stub_server) -> None:
    async def _run():
        stub = _RegularAnswerStub()
        url, server = await stub_server(stub)
        events, emit = _collect_events()
        playback = VirtualPlaybackSink(SR, RealClock(), emit)
        client = DuplexSessionClient(
            url=url,
            playback=playback,
            emit=emit,
            sample_rate=SR,
            frame_samples=FRAME,
            post_audio_timeout_s=10,
            idle_gap_s=0.5,
            no_tts_grace_s=3,
        )
        await client.connect()
        first = await client.run_scenario(_speech_scenario("one", 1.0, [Segment(label="tail", audio=None, duration_seconds=1.0)]))
        await client.send_reset(settle_seconds=0.1)
        second = await client.run_scenario(_speech_scenario("two", 1.0, [Segment(label="tail", audio=None, duration_seconds=1.0)]))
        await client.close()
        server.close()
        await server.wait_closed()
        return stub, first, second

    stub, first, second = asyncio.run(_run())
    assert stub.reset_count == 1
    assert first.scenario == "one" and second.scenario == "two"
    assert second.last_asr_text() == "hello there"


# --------------------------------------------------------------------------
# official server process manager (no model load)
# --------------------------------------------------------------------------

def test_server_command_and_weight_verification(tmp_path: Path) -> None:
    server = OfficialDuplexServer(
        snapshot_dir=tmp_path / "snap",
        base_model_path=tmp_path / "base",
        source_root=tmp_path / "src",
        llm_port=31606,
    )
    cmd = server.build_command()
    assert cmd[1:3] == ["-m", "interclarify.duplex.official_server"]
    assert "--snapshot" in cmd and "--port" in cmd

    import hashlib

    blob = b"fake-weights" * 1024
    snap = tmp_path / "snap"
    snap.mkdir(parents=True)
    (snap / "model_state.safetensors").write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    assert verify_weight_sha256(snap, "model_state.safetensors", digest) == digest
    with pytest.raises(RuntimeError):
        verify_weight_sha256(snap, "model_state.safetensors", "0" * 64)


# --------------------------------------------------------------------------
# expectation evaluation (loaded from the runner script)
# --------------------------------------------------------------------------

def _load_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_p1_2_live_link", ROOT / "scripts" / "run_p1_2_live_link.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluate_expectations() -> None:
    runner = _load_runner_module()
    scenario = Scenario(
        name="demo",
        description="",
        segments=[],
        expect={
            "answer_expected": True,
            "user_asr_contains": "Today",
            "barge_in_stop_expected": True,
        },
    )
    ok = runner.SessionResult(
        scenario="demo",
        asr_texts=["first what day is it today"],
        answer_phase_count=1,
        barge_in_count=1,
        tts_played_samples=SR,
        tts_cancelled_samples=SR,
    )
    checks = runner.evaluate_expectations(scenario, ok)
    assert checks == {"answer": "pass", "user_asr": "pass", "barge_in_stop": "pass"}

    bad = runner.SessionResult(scenario="demo", asr_texts=["nothing"], answer_phase_count=0)
    checks = runner.evaluate_expectations(scenario, bad)
    assert checks["answer"] == "fail"
    assert checks["user_asr"] == "fail"
    assert checks["barge_in_stop"] == "fail"

    silent = Scenario(name="s", description="", segments=[], expect={"expect_no_asr": True})
    assert runner.evaluate_expectations(silent, runner.SessionResult(scenario="s"))["no_asr"] == "pass"
    assert runner.evaluate_expectations(silent, runner.SessionResult(scenario="s", asr_texts=["oops"]))["no_asr"] == "fail"
