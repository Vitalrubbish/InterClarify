"""Local contract tests for the XTurnix pause probe helper functions."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import random
import sys
import unittest

SPEC = importlib.util.spec_from_file_location(
    "xturnix_pause_probe",
    Path(__file__).parents[1] / "scripts/remote/xturnix_pause_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class PauseProbeTests(unittest.TestCase):
    def test_no_pause_is_identity(self) -> None:
        self.assertEqual(probe.with_pause("hello world", "no_pause"), "hello world")

    def test_end_pause_is_appended_once(self) -> None:
        content = probe.with_pause("hello world.", "pause_at_end")
        self.assertEqual(content, "hello world.<|pause|>")
        self.assertEqual(content.count(probe.PAUSE), 1)

    def test_mid_pause_preserves_text_and_adds_two_tokens(self) -> None:
        text = "These are sometimes crowded family beaches with a good range."
        content = probe.with_pause(text, "pause_mid_and_end", offset=18)
        self.assertEqual(content.count(probe.PAUSE), 2)
        self.assertTrue(content.endswith(probe.PAUSE))
        self.assertEqual(content.replace(probe.PAUSE, ""), text)

    def test_offset_is_a_middle_word_boundary(self) -> None:
        text = "one two three four five six seven eight nine ten"
        offset = probe.choose_pause_offset(text, random.Random("fixed"))
        self.assertIsNotNone(offset)
        self.assertEqual(text[offset], " ")
        self.assertGreaterEqual(offset, int(len(text) * 0.2))
        self.assertLessEqual(offset, int(len(text) * 0.8))


if __name__ == "__main__":
    unittest.main()
