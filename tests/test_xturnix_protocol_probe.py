"""Contract tests for the XTX-002 protocol config and probe helpers."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "xturnix_protocol_probe",
    Path(__file__).parents[1] / "scripts/remote/xturnix_protocol_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

CONFIG = Path(__file__).parents[1] / "configs/xturnix_fleurs_test.json"


class ProtocolConfigTests(unittest.TestCase):
    """Reject configs that could silently change the frozen protocol."""

    def load(self):
        return json.loads(CONFIG.read_text())

    def write(self, config):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(config))
        return path

    def test_frozen_config_loads(self):
        config = probe.load_config(CONFIG)
        self.assertEqual(config["asr"]["chunk_ms"], 160)
        self.assertEqual(config["asr"]["transport"]["packet_ms"], 80)
        self.assertEqual(config["xturnix"]["allowed_actions"], ["<|start|>", "<|keep|>"])
        self.assertEqual(config["xturnix"]["max_seq_length"], 2048)
        self.assertFalse(config["pause"]["enabled"])

    def test_rejects_unknown_schema(self):
        config = self.load()
        config["schema"] = "other"
        with self.assertRaises(probe.ProbeError):
            probe.load_config(self.write(config))

    def test_rejects_pause_injection(self):
        config = self.load()
        config["pause"]["enabled"] = True
        with self.assertRaises(probe.ProbeError):
            probe.load_config(self.write(config))

    def test_rejects_transport_or_scheduler_drift(self):
        config = self.load()
        config["asr"]["transport"]["packet_ms"] = 160
        with self.assertRaises(probe.ProbeError):
            probe.load_config(self.write(config))
        config = self.load()
        config["xturnix"]["scheduler"]["max_in_flight"] = 2
        with self.assertRaises(probe.ProbeError):
            probe.load_config(self.write(config))


if __name__ == "__main__":
    unittest.main()
