"""Offline tests for the A4 replayer's evidence and verdict logic."""
from __future__ import annotations

import importlib.util
import asyncio
import json
import tempfile
import unittest
import wave
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/remote/duplex_a4_replay.py"
SPEC = importlib.util.spec_from_file_location("duplex_a4_replay", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class A4ReplayTests(unittest.TestCase):
    """Protect A4 status distinctions and timeline extraction."""

    def timeline(self, token="<|user finish talking|>", stopped=False):
        records = [
            {"event_type": "llm.first_chunk", "monotonic_timestamp": 1.0},
            {"event_type": "tts.started", "monotonic_timestamp": 1.1, "response_id": "r1"},
            {"event_type": "response.update", "monotonic_timestamp": 1.2, "response_id": "r1"},
            {
                "event_type": "duplex.protocol_parsed",
                "monotonic_timestamp": 1.3,
                "state_token": token,
                "raw_output": token,
                "response_id": "r1",
                "reason": (
                    "interruption"
                    if token == "<|user interruption|>"
                    else "control"
                ),
            },
        ]
        if stopped:
            records.append({"event_type": "tts.stopped", "monotonic_timestamp": 1.31, "response_id": "r1"})
        return MODULE.summarize_timeline(records)

    def test_interruption_without_model_token_is_inconclusive(self):
        """A normal response cannot be relabeled as an interruption pass."""
        verdict = MODULE.classify(
            "interruption",
            {
                "status": "COMPLETE",
                "tts_audio_bytes": 100,
                "errors": [],
                "interrupted_response_id": "r1",
            },
            self.timeline(stopped=True),
            False,
        )
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_interruption_requires_wire_token_and_stop(self):
        """The official wire token and a stop event are both required."""
        verdict = MODULE.classify(
            "interruption",
            {
                "status": "COMPLETE",
                "tts_audio_bytes": 100,
                "errors": [],
                "interrupted_response_id": "r1",
            },
            self.timeline("<|user interruption|>", stopped=True),
            True,
        )
        self.assertEqual(verdict, "PASS")

    def test_protocol_error_is_failure(self):
        """A protocol error cannot be hidden by otherwise valid audio."""
        timeline = self.timeline()
        timeline["protocol_errors"] = ["missing_eos"]
        verdict = MODULE.classify(
            "normal",
            {"status": "COMPLETE", "tts_audio_bytes": 100, "errors": []},
            timeline,
            False,
        )
        self.assertEqual(verdict, "FAIL")

    def test_interruption_stop_must_match_response(self):
        """A stop for another response cannot satisfy interruption evidence."""
        timeline = self.timeline("<|user interruption|>", stopped=True)
        timeline["stopped_response_ids"] = ["other-response"]
        verdict = MODULE.classify(
            "interruption",
            {"status": "COMPLETE", "tts_audio_bytes": 100, "errors": [], "interrupted_response_id": "r1"},
            timeline,
            True,
        )
        self.assertEqual(verdict, "FAIL")

    def test_source_manifest_is_deterministic(self):
        """Manifest hashing is stable for a temporary source tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "configs").mkdir()
            (root / "scripts/remote").mkdir(parents=True)
            (root / "xtalk/src/xtalk/duplex_control").mkdir(parents=True)
            (root / "configs/xtalk_duplex_runtime.json").write_text("{}")
            (root / "scripts/remote/duplex_model_service.py").write_text("x")
            (root / "xtalk/src/xtalk/duplex_control/runtime.py").write_text("x")
            spec = importlib.util.spec_from_file_location("manifest", Path(__file__).resolve().parents[1] / "scripts/remote/create_duplex_source_manifest.py")
            manifest_module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(manifest_module)
            first = manifest_module.build_manifest(root)
            second = manifest_module.build_manifest(root)
            self.assertEqual(first["snapshot"], second["snapshot"])
            self.assertEqual(len(first["files"]), 3)

    def test_missing_session_never_reads_another_timeline(self):
        """Keep old session evidence from entering the next verdict."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "old.jsonl").write_text('{}\n')
            self.assertEqual(MODULE.read_timeline(directory, "missing"), (None, []))

    def test_wav_preserves_silence_and_exact_fdb_duration(self):
        """FDB audio stays aligned with input instead of concatenating speech."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.wav"
            capture = MODULE.TimedPcmCapture(path, 1000)
            capture.append(b'\x01\x00' * 100, 0.5)
            capture.close()
            MODULE.normalize_wav_duration(path, 1.0)
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnframes(), 1000)
                pcm = audio.readframes(1000)
            self.assertEqual(pcm[:1000], b'\x00' * 1000)
            self.assertEqual(pcm[1000:1200], b'\x01\x00' * 100)


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    """Exercise paced playback and partial stop acknowledgements."""

    async def test_stop_keeps_played_prefix_and_discards_tail(self):
        """A stop during a chunk retains its heard prefix in WAV and receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            client = MODULE.A4ReplayClient("http://localhost", "ws://localhost", 1, Path(tmp) / "out.wav", 1000)
            client._started = MODULE.time.monotonic()
            client._capture = MODULE.TimedPcmCapture(client.output_wav, 1000)
            sent = []

            class Socket:
                async def send(self, message):
                    sent.append(json.loads(message))

                def __aiter__(self):
                    async def messages():
                        yield json.dumps({"action": "start_tts", "data": {"response_id": "r"}})
                        yield b'\x01\x00' * 1000
                        await asyncio.sleep(0.03)
                        yield json.dumps({"action": "stop_tts", "data": {"response_id": "r"}})
                        await asyncio.sleep(0.01)
                    return messages()

            await client._receive(Socket())
            client._capture.close()
            receipt = next(row for row in sent if row["action"] == "tts_playback_stopped")
            self.assertGreater(receipt["played_audio_ms"], 0)
            self.assertLess(receipt["played_audio_ms"], 1000)
            self.assertFalse(any(row["action"] == "tts_chunk_played" for row in sent))
            with wave.open(str(client.output_wav)) as audio:
                self.assertGreater(audio.getnframes(), 0)
                self.assertLess(audio.getnframes(), 1000)


if __name__ == "__main__":
    unittest.main()
