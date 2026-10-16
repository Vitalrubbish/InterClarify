"""Check benchmark alignment and causality without loading any ASR model."""

import importlib.util
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

import numpy as np


PATH = Path(__file__).parents[1] / "scripts/remote/benchmark_asr_selection.py"
SPEC = importlib.util.spec_from_file_location("asr_selection_benchmark", PATH)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
ALIGN_SPEC = importlib.util.spec_from_file_location("asr_selection_align", PATH.with_name("align_asr_selection.py"))
aligner = importlib.util.module_from_spec(ALIGN_SPEC)
ALIGN_SPEC.loader.exec_module(aligner)


class BenchmarkTests(unittest.TestCase):
    def test_ctc_repeated_character_requires_blank(self):
        probabilities = np.log(np.array([[0.01, 0.99], [0.99, 0.01], [0.01, 0.99]]))
        path, expanded = aligner.ctc_path(probabilities, [1, 1])
        self.assertEqual(list(path), [1, 2, 3])
        self.assertEqual(list(expanded[path]), [1, 0, 1])

    def test_ctc_impossible_alignment_is_rejected(self):
        with self.assertRaises(ValueError):
            aligner.ctc_path(np.log(np.full((2, 2), 0.5)), [1, 1])

    def test_repeated_words_and_edits(self):
        pairs = benchmark.align_words("we can can go now".split(), "we can leave now please".split())
        self.assertEqual(sum(p[2] != "equal" for p in pairs), 3)
        self.assertEqual(sum(p[2] == "equal" for p in pairs), 3)
        repeated = benchmark.align_words(["can", "can"], ["can"])
        self.assertEqual(sum(p[2] == "equal" for p in repeated), 1)
        self.assertEqual(sum(p[2] == "delete" for p in repeated), 1)

    def test_empty_hypothesis_keeps_all_deletions(self):
        pairs = benchmark.align_words(["hello", "there"], [])
        self.assertEqual([p[2] for p in pairs], ["delete", "delete"])

    def test_punctuation_boundaries(self):
        words, marks = benchmark.punctuated_words("Hello, can't you wait?")
        self.assertEqual(words, ["hello", "can't", "you", "wait"])
        self.assertEqual(marks, {0: [","], 3: ["?"]})

    def test_word_latency_retains_coverage_and_negative_values(self):
        sink = SimpleNamespace(text="hello there", source=SimpleNamespace(packets=[]), events=[
            {"text": "hello", "arrival_seconds": 0.4, "eof": False, "rewritten": False},
            {"text": "hello there", "arrival_seconds": 1.3, "eof": False, "rewritten": False}])
        row = {"sample_id": "sample", "reference": "hello there", "duration_seconds": 2.0}
        acoustic = {"error": None, "mean_label_log_probability": -0.2,
                    "words": [{"word": "hello", "end": 0.5}, {"word": "there", "end": 1.0}]}
        with patch.object(benchmark, "NORMALIZE", lambda text: text.lower(), create=True):
            result = benchmark.score_sample(row, sink, acoustic_alignment=acoustic)
        self.assertEqual(result["wer"], 0)
        self.assertTrue(result["alignment_usable"])
        self.assertAlmostEqual(result["estimated_word_latency_seconds"][0], -0.1)
        self.assertEqual(benchmark.summarize([result])["estimated_word_latency_seconds"]["count"], 2)

    def test_empty_failure_counts_toward_wer(self):
        sink = SimpleNamespace(text="", events=[], source=SimpleNamespace(packets=[]))
        row = {"sample_id": "sample", "reference": "hello there", "duration_seconds": 2.0}
        with patch.object(benchmark, "NORMALIZE", lambda text: text.lower(), create=True):
            result = benchmark.score_sample(row, sink, error="timeout")
        summary = benchmark.summarize([result])
        self.assertEqual(summary["wer"], 1.0)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["estimated_word_latency_seconds"]["count"], 0)

    def test_audio_is_unavailable_before_its_packet_time(self):
        source = benchmark.RealtimeAudio(np.ones(1280, dtype=np.float32), 16000, drain_seconds=0)
        source.start()
        try:
            result = source.read(0, 1280)
            self.assertGreaterEqual(time.monotonic() - source.started, 0.075)
            self.assertEqual(len(result), 1280)
            self.assertEqual(len(source.packets), 1)
        finally:
            source.close()

    def test_raw_rewrite_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = benchmark.RealtimeAudio(np.zeros(1280, dtype=np.float32), 16000)
            source.started = time.monotonic()
            sink = benchmark.EventSink(Path(directory) / "events.jsonl", source)
            sink.emit("hello")
            sink.emit("help")
            sink.close()
            self.assertTrue(sink.events[-1]["rewritten"])
            self.assertEqual(sink.events[-1]["text"], "help")
            saved = [json.loads(line) for line in sink.path.read_text().splitlines()]
            self.assertEqual(saved[-1]["text"], "help")


if __name__ == "__main__":
    unittest.main()
