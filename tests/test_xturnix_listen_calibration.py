"""Test causal text extraction, grouped splits, and event-level calibration."""

import importlib.util
from pathlib import Path
import unittest


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load("listen_prepare", "scripts/analysis/prepare_xturnix_listen_calibration.py")
evaluate = load("listen_evaluate", "scripts/remote/evaluate_xturnix_control.py")


def observation(turn, label, probability, split="dev"):
    return {"turn_id": turn, "conversation_id": turn, "target": label,
            "p_start": probability, "split": split}


class ListenCalibrationTests(unittest.TestCase):
    def source(self, turn="001"):
        return {"id": f"en__unseen_1__user_turn_{turn}", "messages": [],
                "words": [{"word": "before", "start": 0.0, "end": 0.8},
                          {"word": "future", "start": 1.05, "end": 1.4}],
                "silence_spans": [{"start": 1.0, "end": 1.5}, {"start": 2.0, "end": 3.0}]}

    def test_future_word_end_controls_visibility(self):
        events, _ = prepare.make_events(self.source())
        self.assertEqual(events[0]["messages"], [{"role": "user", "content": "before"}])
        self.assertEqual(events[0]["target"], "keep")
        self.assertEqual(events[1]["messages"][-1]["content"], "before future")
        self.assertNotIn("target", events[0]["messages"][-1])

    def test_conversation_split_is_shared_by_turns(self):
        left, _ = prepare.make_events(self.source("001"))
        right, _ = prepare.make_events(self.source("002"))
        self.assertEqual({e["split"] for e in left + right}, {left[0]["split"]})

    def test_many_keep_snapshots_do_not_dilute_cutoff(self):
        rows = [observation("a", "keep", 0.6)] + [observation("a", "keep", 0.1)] * 20
        rows += [observation("a", "start", 0.9), observation("b", "start", None)]
        result = evaluate.metrics(rows, 0.5)
        self.assertEqual(result["false_cutoff_rate"], 0.5)
        self.assertEqual(result["endpoint_recall"], 0.5)
        self.assertEqual(result["safe_endpoint_recall"], 0.0)
        self.assertEqual(result["failed_events"], 1)

    def test_threshold_uses_dev_only_and_respects_budget(self):
        rows = [observation("a", "keep", 0.4), observation("a", "start", 0.45),
                observation("b", "keep", 0.1), observation("b", "start", 0.6)]
        threshold, _ = evaluate.choose_threshold(rows, budget=0)
        self.assertEqual(threshold, 0.45)
        self.assertEqual(evaluate.metrics(rows, threshold)["endpoint_recall"], 1.0)
        with self.assertRaisesRegex(ValueError, "development"):
            evaluate.choose_threshold([{**row, "split": "test"} for row in rows])

    def test_empty_text_abstains_without_fake_model_score(self):
        rows = [{**observation("a", "keep", None), "status": "abstain_empty_text"},
                observation("a", "start", 0.6)]
        threshold, _ = evaluate.choose_threshold(rows)
        result = evaluate.metrics(rows, threshold)
        self.assertEqual(result["abstained_empty_text_events"], 1)
        self.assertEqual(result["failed_events"], 0)
        self.assertEqual(sum(result["snapshot_confusion"].values()), 1)


if __name__ == "__main__":
    unittest.main()
