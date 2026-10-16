"""Check text-response measurement independently of GPU inference."""

import importlib.util
from pathlib import Path
import unittest
import asyncio
import json
import sys
import tempfile


PATH = Path(__file__).parents[1] / "scripts/remote/replay_asr_endpoint.py"
SPEC = importlib.util.spec_from_file_location("endpoint_replay", PATH)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class EndpointTests(unittest.TestCase):
    def test_real_runtime_bridge_does_not_read_future_text(self):
        root = PATH.parents[2]
        sys.path.insert(0, str(root / "xtalk/src"))
        sys.path.insert(0, str(root / "scripts/remote"))

        class Model:
            async def stream(self, request):
                yield {"text": "<|user finish talking|>"}
                yield {"text": "Hello."}
                yield {"text": "<|im_end|>"}
                yield {"finish_reason": "stop", "token_ids": [11, 12, 13]}

        row = {"sample_id": "test/one", "boundary_seconds": 0.3, "boundary_interval": [0.2, 0.3]}
        trace = [{"arrival_seconds": 0.01, "text": "Hi"},
                 {"arrival_seconds": 0.7, "text": "Hi future"}]
        try:
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                result = asyncio.run(replay.replay_one(Model(), row, trace, "original", out,
                                                       observation_seconds=0.5))
                self.assertIsNone(result["error"])
                self.assertTrue(result["new_reply_within_2s"])
                requests = json.loads((out / "requests.json").read_text())
                self.assertEqual(requests[0]["history"][-1]["text"], "Hi")
                self.assertEqual(requests[0]["generated_ids"], [11, 12, 13])
        finally:
            sys.path.remove(str(root / "xtalk/src"))
            sys.path.remove(str(root / "scripts/remote"))

    def test_continuing_old_response_is_not_a_new_response(self):
        events = [{"kind": "text", "at": 0.8, "response_id": "old", "text": "Hello"},
                  {"kind": "text", "at": 1.5, "response_id": "old", "text": "Hello there"}]
        metrics = replay.response_metrics(events, 1.0, 13.0)
        self.assertIsNone(metrics["first_new_reply_seconds"])
        self.assertEqual(metrics["cross_boundary_continuation_ids"], ["old"])
        self.assertFalse(metrics["new_reply_within_12s"])

    def test_finish_marker_without_text_is_not_a_response(self):
        metrics = replay.response_metrics([{"kind": "control", "at": 1.1,
            "state_token": "<|user finish talking|>", "response_id": ""}], 1.0, 13.0)
        self.assertIsNone(metrics["first_new_response_id"])

    def test_new_response_can_be_cancelled_later(self):
        events = [{"kind": "text", "at": 1.4, "response_id": "new", "text": "Answer"},
                  {"kind": "cancel", "at": 2.1, "response_id": "new"}]
        metrics = replay.response_metrics(events, 1.0, 13.0)
        self.assertAlmostEqual(metrics["first_new_reply_seconds"], 0.4)
        self.assertTrue(metrics["new_reply_within_2s"])
        self.assertTrue(metrics["first_new_reply_later_cancelled"])

    def test_punctuation_ablation_preserves_other_characters_and_prefixes(self):
        original = ["I", "I'm", "I'm in", "I'm in New-York,", "I'm in New-York, right?"]
        transformed = [replay.without_punctuation(text) for text in original]
        self.assertEqual(transformed[-1], "I'm in New-York right")
        self.assertTrue(all(right.startswith(left) for left, right in zip(transformed, transformed[1:])))


if __name__ == "__main__":
    unittest.main()
