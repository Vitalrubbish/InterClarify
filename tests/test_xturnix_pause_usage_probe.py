"""Check pending pause rendering and one-shot Listen action gating."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/remote"))
from xturnix_pause_usage_probe import PauseState


class PauseUsageTests(unittest.TestCase):
    def test_pause_is_pending_until_user_resumes(self):
        state = PauseState()
        state.update_text("Could you")
        state.pause()
        state.pause()
        self.assertEqual(state.render("pending"), "Could you")
        self.assertEqual(state.render("eager"), "Could you<|pause|>")
        state.update_text("Could you help")
        self.assertEqual(state.render("pending"), "Could you<|pause|> help")
        self.assertFalse(state.gate)
        self.assertEqual(len(state.offsets), 1)

    def test_gate_preserves_keep_and_emits_start_only_once(self):
        state = PauseState()
        state.update_text("Hello")
        self.assertFalse(state.map_start(True))
        state.pause()
        self.assertFalse(state.map_start(False))
        self.assertTrue(state.map_start(True))
        state.pause()
        self.assertFalse(state.map_start(True))

    def test_reference_replay_rejects_nonmonotonic_text(self):
        state = PauseState()
        state.update_text("Hello world")
        with self.assertRaisesRegex(ValueError, "monotonic"):
            state.update_text("Hello")


if __name__ == "__main__":
    unittest.main()
