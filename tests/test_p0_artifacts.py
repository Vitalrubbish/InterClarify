"""P0 artifact tests: configuration merge, manifest determinism, smoke logs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from interclarify.config import (  # noqa: E402
    PROFILES,
    config_digest,
    load_config,
    resolve_paths,
    write_resolved_config,
)
from interclarify.manifest import build_manifest, manifest_fingerprint  # noqa: E402


class ConfigTest(unittest.TestCase):
    def test_profiles_merge_over_base(self) -> None:
        replay = load_config("replay")
        self.assertEqual(replay["profile"], "replay")
        self.assertEqual(replay["device"]["backend"], "cpu")
        self.assertEqual(replay["clock"]["mode"], "virtual")
        # base value survives when profile does not override it
        self.assertEqual(replay["audio"]["sample_rate"], 24000)

        cluster = load_config("cluster")
        self.assertEqual(cluster["device"]["backend"], "cuda")
        self.assertEqual(cluster["clock"]["mode"], "real")

    def test_unknown_profile_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_config("nope")

    def test_digest_is_stable_and_profile_sensitive(self) -> None:
        a = config_digest(load_config("replay"))
        b = config_digest(load_config("replay"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, config_digest(load_config("cluster")))
        self.assertEqual(set(PROFILES), {"local", "replay", "cluster"})

    def test_env_expansion_with_default(self) -> None:
        os.environ.pop("IC_TEST_ROOT", None)
        cfg = load_config(
            "cluster",
            overrides={"paths": {"repo_root": "${IC_TEST_ROOT:-/tmp/fallback}"}},
        )
        self.assertEqual(cfg["paths"]["repo_root"], "/tmp/fallback")

    def test_resolve_paths(self) -> None:
        cfg = load_config("replay")
        paths = resolve_paths(cfg, repo_root=REPO_ROOT)
        self.assertEqual(paths["repo_root"], REPO_ROOT)
        self.assertTrue(paths["model_root"].is_absolute())

    def test_write_resolved_config_roundtrip(self) -> None:
        cfg = load_config("replay")
        with tempfile.TemporaryDirectory() as tmp:
            out = write_resolved_config(cfg, Path(tmp) / "resolved_config.yaml")
            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertIn("profile: replay", text)


class ManifestTest(unittest.TestCase):
    def test_fingerprint_ignores_volatile_fields(self) -> None:
        cfg = load_config("replay")
        with tempfile.TemporaryDirectory() as tmp:
            m1 = build_manifest(cfg, Path(tmp) / "a", repo_root=REPO_ROOT, run_id="ic-one")
            m2 = build_manifest(cfg, Path(tmp) / "b", repo_root=REPO_ROOT, run_id="ic-two")
            self.assertEqual(manifest_fingerprint(m1), manifest_fingerprint(m2))
            self.assertEqual(m1.config_digest, m2.config_digest)

    def test_git_commit_recorded(self) -> None:
        cfg = load_config("replay")
        with tempfile.TemporaryDirectory() as tmp:
            m = build_manifest(cfg, tmp, repo_root=REPO_ROOT)
            self.assertIsNotNone(m.git_commit)
            self.assertRegex(m.git_commit, r"^[0-9a-f]{40}$")


class SmokeTest(unittest.TestCase):
    def _run(self, output_root: Path) -> dict:
        script = REPO_ROOT / "scripts" / "run_p0_smoke.py"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        result = subprocess.run(
            [sys.executable, str(script), "--profile", "replay", "--output-root", str(output_root)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_two_runs_are_structurally_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._run(root / "r1")
            second = self._run(root / "r2")

            def events(run_dir: str):
                path = Path(run_dir) / "events.jsonl"
                return [json.loads(line)["event_type"] for line in path.read_text().splitlines()]

            self.assertEqual(events(first["run_dir"]), events(second["run_dir"]))
            self.assertEqual(
                set(events(first["run_dir"])),
                {"run_start", "audio_input_opened", "audio_chunk_received", "audio_input_closed", "run_end"},
            )

            m1 = json.loads((Path(first["run_dir"]) / "metrics.json").read_text())
            m2 = json.loads((Path(second["run_dir"]) / "metrics.json").read_text())
            self.assertEqual(m1, m2)

            manifest = json.loads((Path(first["run_dir"]) / "manifest.json").read_text())
            self.assertEqual(manifest["profile"], "replay")
            self.assertEqual(manifest["seed"], 0)
            self.assertTrue(manifest["config_digest"])


if __name__ == "__main__":
    unittest.main()
