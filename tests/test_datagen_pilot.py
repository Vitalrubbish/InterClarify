"""Exercise causal boundaries in the semantic data pilot."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "datagen"))
from build_pilot import export_corpus


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads((ROOT / "datagen/scenarios.json").read_text())

    def decision(self, source, branch, key):
        return next(d for d in self.corpus["sources"][source]["branches"][branch]["decisions"] if d["id"] == key)

    def test_views_and_training_blockers(self):
        views, traces, _ = export_corpus(self.corpus)
        self.assertEqual(len(traces), 13)
        self.assertEqual({k: len(v) for k, v in views.items()}, {"soulx": 26, "layer1": 48, "layer2": 16})
        for module, samples in views.items():
            for sample in samples:
                self.assertFalse(sample["eligible_for_training"])
                self.assertTrue(all(m["loss_weight"] == 0 for m in sample["messages"][:2]))
                if module == "soulx":
                    self.assertNotIn("raw_state", sample["input"]["current_user"])
                if sample["protocol_scope"].startswith("future_"):
                    self.assertIn("future_protocol_unimplemented", sample["training_blockers"])
        self.assertFalse(any(v["audit"]["source_id"] in {"scene01", "scene02", "scene03"} for v in views["layer2"]))

    def test_arrival_during_generation_is_not_an_input(self):
        views, _, _ = export_corpus(self.corpus)
        before = next(v for v in views["layer1"] if v["sample_id"] == "scene04/self_resolved/l_before_analysis")
        after = next(v for v in views["layer1"] if v["sample_id"] == "scene04/self_resolved/l_after_analysis")
        self.assertLess(before["audit"]["read_ms"], 800)
        self.assertGreater(before["audit"]["finish_ms"], 800)
        self.assertFalse(before["input"]["external_analysis"])
        self.assertEqual(after["input"]["external_analysis"][0]["basis_frontend"], "p1")
        self.assertIn("专硕", after["input"]["current_user"]["transcript"])
        self.assertEqual(after["target"], {"action": "wait"})

    def test_uncertain_control_and_fixed_error_masking(self):
        views, _, _ = export_corpus(self.corpus)
        uncertain = next(v for v in views["soulx"] if v["audit"]["uncertain"])
        self.assertEqual(uncertain["messages"][-1]["loss_weight"], 0)
        recovery = next(v for v in views["layer1"] if v["sample_id"] == "scene05/fixed_error_recovery/l_correct")
        self.assertIn("十六公斤", recovery["messages"][1]["content"])
        self.assertEqual(recovery["messages"][1]["loss_weight"], 0)
        self.assertIn("应是十四公斤", recovery["target"]["text"])
        self.assertFalse(any(v["target"].get("text") == "一件A和一件B共十六公斤。" for v in views["layer1"]))

    def test_box_answer_by_exhaustive_search(self):
        feasible = [(a + b, a, b, 6 * a + 8 * b, 25 * a + 30 * b) for a in range(1, 5) for b in range(1, 5) if 6 * a + 8 * b <= 20 and 25 * a + 30 * b <= 100]
        maximum = max(row[0] for row in feasible)
        self.assertEqual([row for row in feasible if row[0] == maximum], [(3, 2, 1, 20, 80)])
        views, _, _ = export_corpus(self.corpus)
        final = next(v for v in views["layer1"] if v["sample_id"] == "scene05/progressive/l_final_answer")
        self.assertIn("二十公斤、八十元", final["target"]["text"])

    def test_future_event_is_rejected(self):
        self.decision(3, 0, "l_before_analysis")["seen"].append("a1")
        with self.assertRaisesRegex(ValueError, "Future event"):
            export_corpus(self.corpus)

    def test_hidden_script_is_rejected(self):
        self.decision(0, 0, "l_before_publish")["seen"].append("hidden_tail")
        with self.assertRaisesRegex(ValueError, "Hidden script"):
            export_corpus(self.corpus)

    def test_ordinary_answer_requires_complete(self):
        self.decision(0, 0, "l_answer")["seen"] = ["p2"]
        with self.assertRaisesRegex(ValueError, "without visible effective complete"):
            export_corpus(self.corpus)

    def test_repeated_answer_is_rejected(self):
        self.decision(0, 0, "l_duplicate")["target"] = {"action": "speak", "purpose": "ordinary", "text": "Thank you.", "response_key": "r1"}
        with self.assertRaisesRegex(ValueError, "Repeated ordinary answer"):
            export_corpus(self.corpus)

    def test_future_analysis_basis_is_rejected(self):
        publication = next(e for e in self.corpus["sources"][3]["shared_events"] if e["id"] == "a1")
        publication["payload"]["basis_frontend"] = "p2"
        with self.assertRaisesRegex(ValueError, "Future analysis basis"):
            export_corpus(self.corpus)

    def test_conflicting_shared_prefix_is_rejected(self):
        source = self.corpus["sources"][3]
        shared = next(d for d in source["shared_decisions"] if d["id"] == "c_shared")
        source["shared_decisions"].remove(shared)
        for branch in source["branches"]:
            branch["decisions"].append(deepcopy(shared))
        source["branches"][1]["decisions"][-1]["target"]["intervention"] = "clarification_opportunity"
        with self.assertRaisesRegex(ValueError, "Conflicting shared-prefix"):
            export_corpus(self.corpus)

    def test_cancelled_output_cannot_continue(self):
        self.decision(1, 0, "l_cancelled")["target"] = {"action": "continue_expression", "purpose": "ordinary", "output_id": "o1", "text": "旧正文"}
        with self.assertRaisesRegex(ValueError, "cancelled output"):
            export_corpus(self.corpus)

    def test_played_history_cannot_roll_back(self):
        event = next(e for e in self.corpus["sources"][0]["branches"][0]["events"] if e["id"] == "done1")
        event["payload"]["heard_any"] = False
        event["audit"]["played_text"] = ""
        with self.assertRaisesRegex(ValueError, "Played history rolled back"):
            export_corpus(self.corpus)

    def test_sixth_native_state_is_rejected(self):
        self.decision(0, 0, "c_complete")["target"]["user_state"] = "user_clarify"
        with self.assertRaisesRegex(ValueError, "Invalid controller target"):
            export_corpus(self.corpus)

    def test_active_task_request_is_rejected(self):
        active = next(d for d in self.corpus["sources"][3]["shared_decisions"] if d["id"] == "l_task_active")
        active["target"] = {"action": "request_thinking", "task_id": "think2"}
        with self.assertRaisesRegex(ValueError, "Repeated request for an active task"):
            export_corpus(self.corpus)

    def test_native_controller_cannot_consume_analysis(self):
        self.decision(3, 0, "c_after_branch")["scope"] = "semantic_pilot"
        with self.assertRaisesRegex(ValueError, "Native controller cannot consume CoT"):
            export_corpus(self.corpus)

    def test_clarification_requires_consumed_future_control(self):
        self.decision(3, 2, "l_clarify")["seen"].remove("control_published")
        with self.assertRaisesRegex(ValueError, "without consumed future control boundary"):
            export_corpus(self.corpus)

    def test_phantom_generation_is_rejected(self):
        event = next(e for e in self.corpus["sources"][0]["branches"][0]["events"] if e["id"] == "g1")
        event["payload"]["generated_text"] = "Unsupervised phantom text."
        with self.assertRaisesRegex(ValueError, "Generated history replaced|no preceding expression target"):
            export_corpus(self.corpus)


if __name__ == "__main__":
    unittest.main()
