"""Check stale-score rejection, bounded timing and calibration isolation."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "latency_compare", ROOT / "scripts/analysis/compare_xturnix_latency.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads((ROOT / "configs/xturnix_short_latency.json").read_text())
sys.path.insert(0, str(ROOT / "scripts/remote"))
from xturnix_time_control_probe import EventLog, LatestScorer


def snapshot(at, version=1, changed=0, healthy=True, nonempty=True):
    return {"kind": "snapshot", "at": at, "text_version": version,
            "changed_at": changed, "healthy": healthy, "nonempty": nonempty}


def score(at, version=1, value=.7):
    return {"kind": "score", "at": at, "text_version": version, "p_start": value}


class ShortLatencyContractTest(unittest.TestCase):
    def test_single_inflight_keeps_only_latest_pending_prefix(self):
        first_started, release, third_finished = (threading.Event() for _ in range(3))
        versions = []

        def fake_pipe(messages, state):
            value = messages[-1]["content"]
            versions.append(value)
            if value == "one":
                first_started.set()
                if not release.wait(2):
                    raise RuntimeError("test release deadline")
            if value == "three":
                third_finished.set()
            return {"scores": {"<|start|>": .7}}

        with tempfile.TemporaryDirectory() as temporary:
            log = EventLog(Path(temporary) / "events.jsonl")
            worker = LatestScorer(fake_pipe, [], log)
            worker.start()
            try:
                worker.submit(1, "one")
                self.assertTrue(first_started.wait(2))
                worker.submit(2, "two")
                worker.submit(3, "three")
                release.set()
                self.assertTrue(third_finished.wait(2))
            finally:
                release.set()
                worker.close()
                log.stream.close()
            self.assertEqual(versions, ["one", "three"])
            self.assertEqual(worker.replaced, 1)
            self.assertIsNone(worker.error)

    def test_old_score_cannot_start_new_prefix(self):
        events = [snapshot(0), snapshot(.1, version=2, changed=.1), score(.12)]
        policy = {"family": "text", "times_ms": [0], "thresholds": [.5]}
        self.assertIsNone(MODULE.first_start(events, policy, CONFIG))
        self.assertEqual(MODULE.first_start(events + [score(.13, version=2)], policy, CONFIG), .13)

    def test_new_text_resets_wait_and_unhealthy_input_blocks(self):
        policy = {"family": "time", "times_ms": [300], "thresholds": [0]}
        events = [snapshot(0), snapshot(.2, version=2, changed=.2),
                  snapshot(.4, version=2, changed=.2),
                  snapshot(.5, version=2, changed=.2, healthy=False)]
        self.assertIsNone(MODULE.first_start(events, policy, CONFIG))
        self.assertEqual(MODULE.first_start(events + [snapshot(.55, 2, .2)], policy, CONFIG), .55)

    def test_stale_health_and_empty_text_do_not_start(self):
        policy = {"family": "text", "times_ms": [0], "thresholds": [.5]}
        self.assertIsNone(MODULE.first_start([snapshot(0), score(.2)], policy, CONFIG))
        self.assertIsNone(MODULE.first_start([snapshot(0, nonempty=False), score(.05)], policy, CONFIG))
        self.assertIsNone(MODULE.first_start([
            snapshot(0), {"kind": "observer_error", "at": .02}, score(.05)], policy, CONFIG))

    def test_failed_or_missing_turns_remain_in_denominator(self):
        cases = [{"turn_id": "a", "status": "completed", "word_end": 1},
                 {"turn_id": "b", "status": "failed", "word_end": 1},
                 {"turn_id": "c", "status": "skipped", "word_end": 1}]
        result = MODULE.metrics(cases, {"a": 1.3, "b": 1.2, "c": None}, 500)
        self.assertEqual(result["safe_deadline_hits"], 1)
        self.assertEqual(result["planned_turns"], 3)
        self.assertEqual(result["failed_turns"], 2)

    def test_evaluation_outcomes_do_not_change_selected_policy(self):
        cases = [{"turn_id": name, "status": "completed", "word_end": .25,
                  "silence_start": .3, "partition": group}
                 for name, group in (("a", "calibration"), ("b", "evaluation"))]
        traces = {name: [snapshot(0), score(.05), snapshot(.1), snapshot(.2),
                         snapshot(.3), snapshot(.4), snapshot(.5), snapshot(.8)]
                  for name in ("a", "b")}
        before = MODULE.compare(cases, traces, CONFIG)
        cases[1]["word_end"] = 5
        after = MODULE.compare(cases, traces, CONFIG)
        self.assertEqual([r["policy"] for r in before["results"]],
                         [r["policy"] for r in after["results"]])


if __name__ == "__main__":
    unittest.main()
