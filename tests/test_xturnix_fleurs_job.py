"""Contract tests for the bounded XTurnix FLEURS job entry.

The shell entry is not allowed to touch remote assets before it has validated its
mode and run id.  These tests only exercise local argument handling and syntax;
they never load a model or contact a cluster.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
JOB = REPO_ROOT / "scripts" / "remote" / "run_xturnix_fleurs_job.sh"
SUBMIT = REPO_ROOT / "scripts" / "remote" / "submit_xturnix_fleurs_job.sh"


def run_job(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the job entry with an isolated environment and no extra arguments."""
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent-parathink-test-home",
        "XTURNIX_ROOT": "/nonexistent-parathink-test-root",
    }
    base.update(env)
    return subprocess.run(
        ["bash", str(JOB)],
        capture_output=True,
        text=True,
        env=base,
        timeout=10,
        check=False,
    )


class XTurnixFleursJobEntryTest(unittest.TestCase):
    def test_shell_entries_parse_and_are_executable(self) -> None:
        for script in (JOB, SUBMIT):
            with self.subTest(script=script.name):
                self.assertTrue(script.is_file())
                self.assertTrue(os.access(script, os.X_OK))
                result = subprocess.run(
                    ["bash", "-n", str(script)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_mode_is_rejected_before_any_filesystem_access(self) -> None:
        result = run_job({"XTURNIX_JOB_MODE": "diagnostic"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)

    def test_missing_run_id_is_rejected(self) -> None:
        result = run_job({"XTURNIX_JOB_MODE": "smoke"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("XTURNIX_JOB_RUN_ID", result.stderr)

    def test_path_like_run_id_is_rejected(self) -> None:
        result = run_job(
            {"XTURNIX_JOB_MODE": "formal", "XTURNIX_JOB_RUN_ID": "../escape"}
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid run id", result.stderr)


if __name__ == "__main__":
    unittest.main()
