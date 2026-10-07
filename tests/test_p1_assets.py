from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "remote" / "prepare_p1_assets.py"


def test_prepare_assets_dry_run_resolves_pinned_versions(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    artifact_root = tmp_path / "artifacts"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(ROOT),
            "--model-root",
            str(model_root),
            "--artifact-root",
            str(artifact_root),
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    plan = json.loads(result.stdout)
    assert plan["repo_commit"] == "42893024ca90c8de8ac3ed624467ebc123512ff8"
    assert plan["hf_revision"] == "31c038ece2f006a28722dd60d1df3868fbb2cc42"
    assert plan["weight_filename"] == "model_state.safetensors"
    assert plan["download_base_model"] is True
    assert plan["provider"] == "huggingface"


def test_prepare_assets_dry_run_accepts_modelscope_provider(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(ROOT),
            "--model-root",
            str(tmp_path / "models"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--provider",
            "modelscope",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    plan = json.loads(result.stdout)
    assert plan["provider"] == "modelscope"


def test_prepare_assets_rejects_model_root_inside_checkout(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(ROOT),
            "--model-root",
            str(ROOT / "models"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--dry-run",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "model root must be an absolute path outside the repository" in result.stderr
