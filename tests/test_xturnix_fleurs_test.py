"""Freeze/verify and replay-contract tests for the XTurnix FLEURS entry."""

import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "xturnix_fleurs_test",
    Path(__file__).parents[1] / "scripts/remote/xturnix_fleurs_test.py",
)
fleurs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fleurs
SPEC.loader.exec_module(fleurs)


def write_tsv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join("\t".join(row) for row in rows) + "\n",
        encoding="utf-8",
    )


class FleursFreezeTests(unittest.TestCase):
    """Check the deterministic selection, reuse path and failure on tampering."""

    def make_reuse_dataset(self, root):
        import soundfile as sf
        import numpy as np

        test_rows = [
            ["1", "alpha.wav", "Hello world.", "Hello world", "12", "16000", "FEMALE"],
            ["2", "beta.wav", "Second sample.", "Second sample", "14", "16000", "MALE"],
            ["3", "gamma.wav", "Third sample.", "Third sample", "13", "16000", "FEMALE"],
        ]
        dev_row = ["4", "warmup.wav", "Warm up.", "Warm up", "8", "16000", "MALE"]
        selected = fleurs.select_rows(test_rows, 2)
        selected_dev = fleurs.select_rows([dev_row], 1)
        reuse = root / "reuse"
        write_tsv(reuse / "source/en_us/test.tsv", test_rows)
        write_tsv(reuse / "source/en_us/dev.tsv", [dev_row])
        tone = np.zeros(16000, dtype=np.float32)
        for _, row in selected:
            path = reuse / "audio/test" / row[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(path), tone, 16000, subtype="PCM_16")
        path = reuse / "audio/dev" / selected_dev[0][1][1]
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), tone, 16000, subtype="PCM_16")
        expected = fleurs.Expectations(
            test_count=2,
            dev_count=1,
            test_duration_seconds=2.0,
            test_normalized_words=4,
            first_file=selected[0][1][1],
            last_file=selected[-1][1][1],
            dev_file=selected_dev[0][1][1],
        )
        return reuse, expected

    def test_selection_is_sha256_of_filename(self):
        rows = [["1", "a.wav", "a", "a", "1", "1", "F"], ["2", "b.wav", "b", "b", "1", "1", "M"]]
        selected = fleurs.select_rows(rows, 2)
        self.assertEqual(
            [row[1] for _, row in selected],
            [row[1] for row in sorted(rows, key=lambda row: fleurs.selection_hash(row[1]))],
        )
        with self.assertRaises(ValueError):
            fleurs.select_rows(rows, 3)

    def test_prepare_and_verify_reused_subset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reuse, expected = self.make_reuse_dataset(root)
            target = root / "workspace"
            preparer = fleurs.DatasetPreparer(target, reuse_dir=reuse, expected=expected)
            report = preparer.prepare()
            self.assertTrue(report["ok"])
            self.assertEqual(report["source_mode"], "reuse")
            self.assertFalse(report["verification"]["old_manifest_available"])
            self.assertTrue((target / "dataset/fleurs_en_us/manifest.json").is_file())
            self.assertTrue((target / "dataset/fleurs_en_us/historical_asr_baseline.json").is_file())
            verified = fleurs.verify_data(target, expected=expected)
            self.assertEqual(verified["test_samples"], 2)
            self.assertTrue(verified["historical_baseline_verified"])

    def test_verify_rejects_tampered_audio(self):
        import soundfile as sf
        import numpy as np

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reuse, expected = self.make_reuse_dataset(root)
            target = root / "workspace"
            fleurs.DatasetPreparer(target, reuse_dir=reuse, expected=expected).prepare()
            audio = target / "dataset/fleurs_en_us/audio/test" / expected.first_file
            sf.write(str(audio), np.ones(16000, dtype=np.float32) * 0.5, 16000, subtype="PCM_16")
            with self.assertRaises(ValueError):
                fleurs.verify_manifest(
                    target / "dataset/fleurs_en_us/manifest.json", expected=expected
                )
            with self.assertRaises(RuntimeError):
                fleurs.DatasetPreparer(target, reuse_dir=reuse, expected=expected).prepare()

    def test_historical_baseline_matches_documented_values(self):
        baseline = fleurs.historical_baseline()
        self.assertEqual(baseline["source_commit"], "f6ad9d9ba04e4e046dcfcdd480b5343165466046")
        self.assertEqual(baseline["measurable_words"], 3068)
        self.assertEqual(baseline["reference_words"], 4324)
        self.assertAlmostEqual(baseline["p50_ms"], 413.58285225927827)
        self.assertAlmostEqual(baseline["p95_ms"], 1032.6687976904216)
        self.assertEqual(json.loads(json.dumps(baseline)), baseline)


CONFIG = Path(__file__).parents[1] / "configs" / "xturnix_fleurs_test.json"


class ReplayFakes:
    """Small deterministic stand-ins for the two model services."""

    class Asr:
        def __init__(self, words=None, fail_first_speech=False):
            self.words = words or ["alpha", "beta", "gamma", "delta", "epsilon"]
            self.fail_first_speech = fail_first_speech
            self.closed = set()
            self.ended = set()
            self.created = []
            self.speech_packets = {}
            self.received = {}
            self.versions = {}
            self.texts = {}
            self.end_stream_calls = 0

        def create(self):
            identity = f"s{len(self.created) + 1}"
            self.created.append(identity)
            self.speech_packets[identity] = 0
            self.received[identity] = []
            self.versions[identity] = 0
            self.texts[identity] = ""
            return identity

        def snapshot(self, identity):
            return {
                "session_id": identity,
                "prefix_version": self.versions[identity],
                "text": self.texts[identity],
                "raw_text": self.texts[identity],
                "ended": identity in self.ended,
            }

        def recognize(self, session, pcm, *, is_final=False, end_stream=False):
            if end_stream:
                self.end_stream_calls += 1
                self.ended.add(session)
                return self.snapshot(session)
            self.received[session].append(len(pcm) if any(pcm) else 0)
            if any(pcm):
                if self.fail_first_speech:
                    self.fail_first_speech = False
                    raise RuntimeError("simulated ASR transport failure")
                self.speech_packets[session] += 1
                if self.speech_packets[session] % 4 == 0:
                    self.versions[session] = min(
                        self.versions[session] + 1, len(self.words)
                    )
                    self.texts[session] = " ".join(
                        self.words[: self.versions[session]]
                    )
            return self.snapshot(session)

        def result(self, session):
            if session in self.closed:
                return 404, {"detail": "unknown"}
            return 200, self.snapshot(session)

        def close(self, session):
            self.closed.add(session)
            return 200, {"ok": True}

    class Controller:
        def __init__(self, start_on="beta", delay=0.0, release=None):
            self.start_on = start_on
            self.delay = delay
            self.release = release
            self.inputs = []
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def evaluate(self, text, state):
            with self.lock:
                self.inputs.append(text)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                if self.release is not None:
                    self.release.wait(5)
                elif self.delay:
                    time.sleep(self.delay)
                return {
                    "action": "<|start|>" if self.start_on in text else "<|keep|>",
                    "scores": {
                        "<|start|>": 0.8 if self.start_on in text else 0.2,
                        "<|keep|>": 0.2 if self.start_on in text else 0.8,
                    },
                    "normalized_input": text,
                    "state": state,
                }
            finally:
                with self.lock:
                    self.active -= 1


class ReplayContractTests(unittest.TestCase):
    """Check queue bounds, real-clock phases, trace traceability and isolation."""

    def settings(self, **overrides):
        values = {
            "packet_ms": 5,
            "tail_packets": 3,
            "poll_interval_seconds": 0.002,
            "asr_timeout_seconds": 1.0,
            "control_timeout_seconds": 0.2,
            "min_free_bytes": 0,
        }
        values.update(overrides)
        return fleurs.ReplaySettings(**values)

    def make_run(self, folder, samples, asr, controller, settings, name="run"):
        import numpy as np
        import soundfile as sf

        root = Path(folder) / f"workspace-{name}"
        data = root / "dataset" / "fleurs_en_us"
        manifest_samples = []
        for index, sample_id in enumerate(samples):
            path = data / "audio" / "test" / f"{sample_id}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(
                str(path),
                np.full(1600, 0.25, dtype=np.float32),
                16000,
                subtype="PCM_16",
            )
            manifest_samples.append(
                {
                    "sample_id": f"test/{sample_id}",
                    "split": "test",
                    "relative_path": f"audio/test/{sample_id}.wav",
                    "audio_sha256": fleurs.sha256_file(path),
                }
            )
        manifest = data / "manifest.json"
        manifest.write_text(
            json.dumps({"schema": fleurs.MANIFEST_SCHEMA, "samples": manifest_samples})
        )
        output = root / "runs" / name
        runner = fleurs.ReplayRunner(
            output,
            CONFIG,
            manifest,
            manifest_samples,
            settings,
            asr,
            controller,
            split="test",
        )
        return runner, output

    def read_trace(self, path):
        events = [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        return events

    def test_default_contract_uses_five_second_tail(self):
        config = fleurs.load_replay_config(CONFIG)
        settings = fleurs.ReplaySettings.from_config(config)
        self.assertEqual(settings.packet_ms, 80)
        self.assertEqual(settings.tail_packets, 63)
        self.assertEqual(settings.main_window_seconds, 5.0)
        self.assertEqual(fleurs.tail_packet_count(5.0, 80), 63)
        config["pause"]["enabled"] = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(config))
            with self.assertRaises(fleurs.ReplayError):
                fleurs.load_replay_config(path)

    def test_one_in_flight_latest_prefix_and_post_cutoff_result(self):
        release = threading.Event()
        controller = ReplayFakes.Controller(release=release)
        with tempfile.TemporaryDirectory() as folder:
            recorder = fleurs.TraceRecorder(
                Path(folder) / "trace.jsonl", {"schema": fleurs.TRACE_SCHEMA}
            )
            phases = fleurs.PhaseTracker(recorder)
            scheduler = fleurs.ControlScheduler(
                controller, self.settings(), recorder, phases
            )
            scheduler.start()
            scheduler.submit(
                {"prefix_version": 1, "text": "alpha"}, time.monotonic(), 1
            )
            deadline = time.monotonic() + 1
            while controller.inputs == [] and time.monotonic() < deadline:
                time.sleep(0.01)
            scheduler.submit(
                {"prefix_version": 2, "text": "alpha beta"}, time.monotonic(), 2
            )
            scheduler.submit(
                {"prefix_version": 3, "text": "alpha beta gamma"}, time.monotonic(), 3
            )
            closer = threading.Thread(target=lambda: scheduler.close(time.monotonic()))
            closer.start()
            time.sleep(0.05)
            release.set()
            closer.join(5)
            self.assertFalse(closer.is_alive())
            recorder.close()
            self.assertFalse(scheduler.stuck)
            self.assertEqual(scheduler.max_observed_in_flight, 1)
            self.assertEqual(controller.max_active, 1)
            self.assertEqual(scheduler.started, 1)
            self.assertEqual(scheduler.superseded, 1)
            self.assertEqual(scheduler.dropped, 1)
            self.assertEqual(scheduler.completed, 1)
            self.assertEqual(scheduler.late_completions, 1)
            events = [
                json.loads(line)
                for line in (Path(folder) / "trace.jsonl").read_text().splitlines()
            ]
            self.assertTrue(any(event["event"] == "control_superseded" for event in events))
            dropped = [event for event in events if event["event"] == "control_dropped"]
            self.assertEqual([event["input_version"] for event in dropped], [3])
            completed = [
                event for event in events if event["event"] == "control_completed"
            ]
            self.assertEqual(len(completed), 1)
            self.assertFalse(completed[0]["under_cutoff"])

    def test_replay_trace_phases_and_no_reference_injection(self):
        asr = ReplayFakes.Asr()
        controller = ReplayFakes.Controller()
        with tempfile.TemporaryDirectory() as folder:
            runner, output = self.make_run(
                folder, ["one"], asr, controller, self.settings()
            )
            report = runner.run()
            self.assertEqual(report["counts"]["planned"], 1)
            self.assertEqual(report["counts"]["completed"], 1)
            status = json.loads((output / "status.json").read_text())["items"][0]
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["file_packets_sent"], 20)
            self.assertEqual(status["tail_packets_sent"], 3)
            self.assertGreater(status["actions"].get("<|start|>", 0), 0)
            events = self.read_trace(output / status["trace_path"])
            packet_events = [
                event for event in events if event["event"] == "asr_packet_sent"
            ]
            self.assertEqual(
                [(event["kind"], event["packet_index"]) for event in packet_events],
                [("file_audio", index) for index in range(20)]
                + [("tail_silence", index) for index in range(3)],
            )
            self.assertEqual(asr.received["s1"][:20], [160] * 20)
            self.assertEqual(asr.received["s1"][-3:], [0, 0, 0])
            observations = [
                event for event in events if event["event"] == "asr_observation"
            ]
            observed_times = [event["monotonic"] for event in observations]
            self.assertEqual(observed_times, sorted(observed_times))
            observed_texts = {event["text"] for event in observations if event["text"]}
            self.assertTrue(controller.inputs)
            self.assertTrue(set(controller.inputs).issubset(observed_texts))
            self.assertFalse(
                any("REFERENCE" in text for text in controller.inputs),
                "reference text must never reach the online controller",
            )
            completed = [
                event for event in events if event["event"] == "control_completed"
            ]
            self.assertTrue(completed)
            self.assertTrue(all(event["under_cutoff"] for event in completed))
            phases = status["phase_times"]
            self.assertGreater(phases["file_audio_complete"], phases["file_audio"])
            self.assertGreaterEqual(
                phases["post_cutoff"] - phases["tail_silence"], 0.015 - 1e-3
            )
            self.assertGreater(phases["eof_request_started"], phases["post_cutoff"])
            self.assertGreaterEqual(phases["eof_request_started"], phases["eof_drain"])
            self.assertIn(phases["closed"], phases.values())
            self.assertEqual(asr.created, ["s1"])
            self.assertIn("s1", asr.closed)
            self.assertFalse((output / "config.json").read_text() != CONFIG.read_text())

    def test_failed_sample_is_recorded_and_next_session_is_isolated(self):
        asr = ReplayFakes.Asr(fail_first_speech=True)
        controller = ReplayFakes.Controller()
        with tempfile.TemporaryDirectory() as folder:
            runner, output = self.make_run(
                folder, ["one", "two"], asr, controller, self.settings()
            )
            report = runner.run()
            self.assertEqual(report["counts"]["planned"], 2)
            self.assertEqual(report["counts"]["failed"], 1)
            self.assertEqual(report["counts"]["completed"], 1)
            items = json.loads((output / "status.json").read_text())["items"]
            self.assertEqual([item["status"] for item in items], ["failed", "completed"])
            self.assertIn("simulated ASR transport failure", items[0]["failure_reason"])
            self.assertEqual(asr.created, ["s1", "s2"])
            self.assertIn("s1", asr.closed)
            self.assertIn("s2", asr.closed)
            second = self.read_trace(output / items[1]["trace_path"])
            creations = [
                event for event in second if event["event"] == "asr_session_created"
            ]
            self.assertEqual(creations[0]["session_id"], "s2")

    def test_stuck_control_aborts_instead_of_reusing_the_session(self):
        release = threading.Event()
        controller = ReplayFakes.Controller(release=release)
        asr = ReplayFakes.Asr()
        with tempfile.TemporaryDirectory() as folder:
            runner, output = self.make_run(
                folder, ["one", "two"], asr, controller, self.settings()
            )
            report = runner.run()
            release.set()
            self.assertEqual(report["counts"]["planned"], 2)
            self.assertEqual(report["counts"]["failed"], 1)
            self.assertEqual(report["counts"]["skipped"], 1)
            items = json.loads((output / "status.json").read_text())["items"]
            self.assertTrue(items[0]["fatal_reason"])
            self.assertEqual(items[1]["status"], "skipped")
            self.assertIn("not started after fatal sample", items[1]["failure_reason"])
            self.assertEqual(asr.created, ["s1"])

    def test_token_change_distinguishes_lexical_and_punctuation_updates(self):
        appended, revised = fleurs.token_change(("Don",), ("Don't",))
        self.assertEqual(appended, ["Don't"])
        self.assertTrue(revised)
        appended, revised = fleurs.token_change(("Hello",), ("Hello", "world"))
        self.assertEqual(appended, ["world"])
        self.assertFalse(revised)
        appended, revised = fleurs.token_change(("Hello", "world"), ("Hello", "world"))
        self.assertEqual(appended, [])
        self.assertFalse(revised)


if __name__ == "__main__":
    unittest.main()
