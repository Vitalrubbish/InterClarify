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

    def test_response_latency_ignores_listening_and_record_order(self):
        """Only the matching answer request contributes its first token."""
        records = [
            {'event_type': 'llm.first_chunk', 'monotonic_timestamp': 1, 'request_id': 'listen'},
            {'event_type': 'tts.started', 'monotonic_timestamp': 5.1, 'request_id': 'answer', 'response_id': 'r'},
            {'event_type': 'llm.first_chunk', 'monotonic_timestamp': 5, 'request_id': 'answer'},
            {'event_type': 'response.update', 'monotonic_timestamp': 6, 'response_id': 'r'},
        ]
        result = MODULE.summarize_timeline(records)
        self.assertAlmostEqual(result['latencies']['llm_to_tts_started_seconds'], .1)
        records[1].pop('request_id')
        self.assertIsNone(MODULE.summarize_timeline(records)['response_latencies'][0]['llm_to_tts_started_seconds'])

    def test_client_separates_old_answer_from_interruption_reply(self):
        """A late old PCM cannot become the interruption reply."""
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp)
            (sample / 'interrupt.json').write_text(json.dumps([{'timestamp': [2, 4]}]))
            events = [{'action': action, 'seconds': seconds + 10, 'data': {'response_id': rid}}
                      for action, seconds, rid in [('start_tts', 1, 'old'), ('pcm_received', 4.1, 'old'),
                                                  ('stop_tts', 4.2, 'old'), ('start_tts', 5, 'new'),
                                                  ('pcm_received', 5.5, 'new'), ('playback_started', 5.6, 'new')]]
            report = {'input_start_seconds': 10, 'input_audio_seconds': 5, 'events': events}
            result = MODULE.summarize_client_responses(report, sample)
            self.assertEqual(result['latencies']['interruption_end']['response_id'], 'new')
            self.assertAlmostEqual(result['latencies']['interruption_end']['to_pcm_received_seconds'], 1.5)
            self.assertAlmostEqual(result['latencies']['interruption_stop'][0]['seconds'], 2.2)
            self.assertTrue(result['responses'][1]['playback_started_in_tail'])

    def timeline(self, token="<|user finish talking|>", stopped=False, stop_reason=None):
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
            records.append(
                {
                    "event_type": "turn.tts_stop_requested",
                    "monotonic_timestamp": 1.3,
                    "response_id": "r1",
                    "reason": token if stop_reason is None else stop_reason,
                }
            )
            records.append({"event_type": "tts.stopped", "monotonic_timestamp": 1.31, "response_id": "r1"})
        return MODULE.summarize_timeline(records)

    def frozen_report(self, **overrides):
        """Return a COMPLETE interruption report whose audio stopped acoustically."""
        report = {
            "status": "COMPLETE",
            "tts_audio_bytes": 100,
            "errors": [],
            "interrupted_response_id": "r1",
            "interrupted_audio_frozen": True,
        }
        report.update(overrides)
        return report

    def test_interruption_without_model_token_is_inconclusive(self):
        """A normal response cannot be relabeled as an interruption pass."""
        verdict = MODULE.classify(
            "interruption",
            self.frozen_report(),
            self.timeline(stopped=True),
            False,
        )
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_interruption_requires_wire_token_and_stop(self):
        """The official wire token, a matching reset and silence are all required."""
        verdict = MODULE.classify(
            "interruption",
            self.frozen_report(),
            self.timeline("<|user interruption|>", stopped=True),
            True,
        )
        self.assertEqual(verdict, "PASS")

    def test_interruption_requires_acoustic_silence(self):
        """A reset receipt alone cannot pass while the response keeps speaking."""
        verdict = MODULE.classify(
            "interruption",
            self.frozen_report(interrupted_audio_frozen=False),
            self.timeline("<|user interruption|>", stopped=True),
            True,
        )
        self.assertEqual(verdict, "FAIL")

    def test_interruption_teardown_stop_is_not_evidence(self):
        """A session shutdown stop cannot be presented as an interruption reset."""
        timeline = self.timeline("<|user interruption|>", stopped=True, stop_reason="shutdown")
        self.assertEqual(timeline["interruption_stop_response_ids"], [])
        self.assertEqual(timeline["teardown_stop_response_ids"], ["r1"])
        self.assertEqual(timeline["stopped_response_ids"], ["r1"])
        # The marker was emitted, so a teardown-only stop is a real failure.
        verdict = MODULE.classify("interruption", self.frozen_report(), timeline, False)
        self.assertEqual(verdict, "FAIL")
        # Without any marker the same stop stays inconclusive instead of passing.
        no_marker = MODULE.classify(
            "interruption",
            self.frozen_report(),
            self.timeline(stopped=True, stop_reason="shutdown"),
            False,
        )
        self.assertEqual(no_marker, "INCONCLUSIVE")

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
        timeline["interruption_stop_response_ids"] = ["other-response"]
        verdict = MODULE.classify(
            "interruption",
            self.frozen_report(),
            timeline,
            True,
        )
        self.assertEqual(verdict, "FAIL")

    def playback_timeline(self, updates, finish=None, asr=None, started=1.1):
        records = [{"event_type": "tts.started", "monotonic_timestamp": started, "response_id": "r1"}]
        for index, text in enumerate(updates):
            records.append(
                {
                    "event_type": "response.update",
                    "monotonic_timestamp": started + 0.1 * (index + 1),
                    "response_id": "r1",
                    "text": text,
                }
            )
        for offset, text in enumerate(finish or []):
            records.append(
                {
                    "event_type": "response.finish",
                    "monotonic_timestamp": started + 0.5 + 0.1 * offset,
                    "response_id": "r1",
                    "text": text,
                }
            )
        for kind, timestamp in asr or []:
            records.append({"event_type": kind, "monotonic_timestamp": timestamp})
        return MODULE.summarize_timeline(records)

    def test_played_text_must_be_monotonic(self):
        """Confirmed playback text can only grow by prefix, never shrink."""
        timeline = self.playback_timeline(["你", "你好"])
        self.assertTrue(timeline["played_text_monotonic"])
        passed = MODULE.classify(
            "normal",
            {"status": "COMPLETE", "tts_audio_bytes": 100, "errors": []},
            timeline,
            False,
        )
        self.assertEqual(passed, "PASS")
        broken = self.playback_timeline(["你好", "你"])
        self.assertFalse(broken["played_text_monotonic"])
        verdict = MODULE.classify(
            "normal",
            {"status": "COMPLETE", "tts_audio_bytes": 100, "errors": []},
            broken,
            False,
        )
        self.assertEqual(verdict, "FAIL")

    def test_unplayed_tail_is_not_counted_as_played(self):
        """Final settlement text cannot exceed the last confirmed prefix."""
        timeline = self.playback_timeline(["你好"], finish=["你好世界"])
        self.assertFalse(timeline["unplayed_tail_excluded"])
        verdict = MODULE.classify(
            "normal",
            {"status": "COMPLETE", "tts_audio_bytes": 100, "errors": []},
            timeline,
            False,
        )
        self.assertEqual(verdict, "FAIL")
        trimmed = self.playback_timeline(["你好世界"], finish=["你好"])
        self.assertTrue(trimmed["unplayed_tail_excluded"])

    def test_asr_updates_during_playback_window(self):
        """Only ASR updates inside the playback window are counted."""
        timeline = self.playback_timeline(
            ["你好"],
            finish=["你好"],
            asr=[("asr.result_partial", 1.3), ("asr.result_partial", 5.0)],
        )
        self.assertEqual(timeline["asr_updates_during_playback"], 1)

    def test_pause_scenario_passes_with_two_segments(self):
        """A pause scenario with a settled answer passes the base gate."""
        timeline = self.playback_timeline(["好的"])
        verdict = MODULE.classify(
            "pause",
            {
                "status": "COMPLETE",
                "tts_audio_bytes": 100,
                "errors": [],
                "response_finished": True,
            },
            timeline,
            False,
        )
        self.assertEqual(verdict, "PASS")

    def test_scenario_audio_overrides_are_parsed(self):
        """Per-scenario overrides name one path, or two for pause."""
        mapping = MODULE.parse_scenario_audio(["normal=/a.wav", "pause=/b.wav,/c.wav"])
        self.assertEqual([path.name for path in mapping["pause"]], ["b.wav", "c.wav"])
        self.assertEqual(
            [path.name for path in MODULE.scenario_audio_paths("normal", mapping, Path("/d.wav"))],
            ["a.wav"],
        )
        self.assertEqual(
            [path.name for path in MODULE.scenario_audio_paths("multi_question", mapping, Path("/d.wav"))],
            ["d.wav"],
        )
        with self.assertRaises(ValueError):
            MODULE.parse_scenario_audio(["broken-without-equals"])

    def test_source_manifest_is_deterministic(self):
        """Manifest hashing is stable for a temporary source tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "configs").mkdir()
            (root / "scripts/remote").mkdir(parents=True)
            (root / "xtalk/src/xtalk/duplex_control").mkdir(parents=True)
            (root / "configs/xtalk_duplex_x2_runtime.json").write_text("{}")
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

    async def test_diagnostic_silence_drain_preserves_original_fdb_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = MODULE.A4ReplayClient('http://localhost', 'ws://localhost', 1,
                Path(tmp) / 'out.wav', fdb_tail_seconds=0.08, fdb_tail_audio=True)
            client._started = 10.0
            sent = []

            async def send(ws, pcm, index):
                sent.append(pcm)
                return 10.0, 10.18

            client._send_turn_input = send
            original = b'\x01\x00' * 1600
            report, passed = await client._run_fdb(None, original)
            self.assertTrue(passed)
            self.assertEqual(sent, [original + b'\x00\x00' * 1280])
            self.assertEqual(report['input_audio_seconds'], 0.1)
            self.assertTrue(report['diagnostic_tail_audio'])

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
