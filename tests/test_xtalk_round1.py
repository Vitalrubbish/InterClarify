"""Offline regressions for model provenance and round-one streaming probes."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/remote/run_xtalk_round1.py"
SPEC = importlib.util.spec_from_file_location("round1", SCRIPT)
round1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(round1)


class RoundOneTest(unittest.TestCase):
    """Protect immutable model locks, allocated GPUs, and duplex collection."""

    def test_gpu_mapping_stays_within_allocation(self) -> None:
        """Logical indices resolve to the job's visible IDs, including UUIDs."""
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "GPU-one,GPU-two"}):
            round1.select_gpu(1)
            self.assertEqual(round1.os.environ["CUDA_VISIBLE_DEVICES"], "GPU-two")
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "5"}):
            with self.assertRaises(ValueError):
                round1.select_gpu(1)
        with self.assertRaises(ValueError):
            round1.select_gpu(-1)

    def test_download_reuses_revision_and_rejects_model_changes(self) -> None:
        """A second download never resolves floating main again."""
        calls = []

        class FakeApi:
            """Return a known immutable model revision."""

            def model_info(self, model_id, revision):
                """Count model revision lookups."""
                calls.append((model_id, revision))
                return types.SimpleNamespace(sha="a" * 40)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            downloads = []

            def fake_download(**kwargs):
                """Capture the exact revision requested for each download."""
                downloads.append(kwargs["revision"])
                return str(snapshot)

            module = types.SimpleNamespace(HfApi=FakeApi, snapshot_download=fake_download)
            config = {"models": {"asr": {"model_id": "test/asr", "revision": None}}}
            with patch.dict("sys.modules", {"huggingface_hub": module}):
                round1.download_models(config, root)
                round1.download_models(config, root)
                self.assertEqual(calls, [("test/asr", None)])
                self.assertEqual(downloads, ["a" * 40, "a" * 40])
                self.assertEqual(round1.model_path(config, root, "asr"), snapshot)
                config["models"]["asr"]["model_id"] = "test/other"
                with self.assertRaises(ValueError):
                    round1.download_models(config, root)

    def test_tts_receives_audio_before_text_is_flushed(self) -> None:
        """Receive audio concurrently instead of buffering all text first."""
        class FakeTTS:
            """Produce audio on first text and complete only after flush."""

            output_sample_rate = 48000

            def __init__(self, **kwargs):
                """Create independent streaming signals."""
                self.ready = asyncio.Event()
                self.finished = asyncio.Event()

            async def start(self):
                """Start a test session."""

            async def append_text(self, text):
                """Make the first audio chunk available."""
                self.ready.set()

            async def flush(self):
                """Permit synthesis completion."""
                self.finished.set()

            async def stop(self):
                """Close the test session."""

            async def audio_stream(self):
                """Yield before and after the text flush boundary."""
                await self.ready.wait()
                yield b"\x01\x00" * 100
                await self.finished.wait()
                yield b"\x02\x00" * 100

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.wav"
            reference.write_bytes(b"test-reference")
            (root / "models.lock.json").write_text('{"models": {}}')
            args = argparse.Namespace(
                config=round1.DEFAULT_CONFIG, output=root / "result", reference=reference,
                gap_seconds=0.02, text=["first", "second"], url=None, timeout_seconds=1,
                model_root=root,
            )
            config = round1.read_config(args.config)
            module = types.SimpleNamespace(MossTTSRealtime=FakeTTS)
            with patch.dict("sys.modules", {"xtalk.models.tts.moss_tts_realtime": module}):
                asyncio.run(round1.tts_smoke(config, args))
            report = json.loads((args.output / "tts_report.json").read_text())
            self.assertTrue(report["audio_before_flush"])
            self.assertEqual(report["audio_chunks"], 2)
            with wave.open(str(args.output / "tts.wav")) as audio:
                self.assertEqual(audio.getframerate(), 48000)
                self.assertEqual(audio.getnframes(), 200)


if __name__ == "__main__":
    unittest.main()
