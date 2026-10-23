"""Freeze/verify tests for the XTurnix FLEURS data entry points."""

import importlib.util
import json
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
