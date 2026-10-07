"""Reproducible run manifest for InterClarify (P0).

Every run is identified by a unique ``run_id`` and described by a manifest
that records what the experiment can be reproduced from: code commit, config
digest, model revision, random seed, resolved device, start/end time and the
output directory.  P0 fixes this format; later phases only add fields.

The manifest intentionally records *provenance*, never hidden task truth, so
it is safe to keep alongside online event logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .config import config_digest

MANIFEST_FILENAME = "manifest.json"
ENVIRONMENT_FILENAME = "environment.txt"
UTC = timezone.utc


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def new_run_id(prefix: str = "ic") -> str:
    """Return a sortable, unique run id such as ``ic-20261007T153000-<8hex>``."""
    stamp = utc_now().strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def collect_git_info(repo_root: Path | str) -> Dict[str, Any]:
    """Collect commit hash and dirty flag from the repository at ``repo_root``."""
    repo_root = Path(repo_root)

    def _git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "git_commit": commit,
        "git_dirty": bool(status) if status is not None else None,
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
    }


def _optional_import_version(module: str) -> Optional[str]:
    try:
        mod = __import__(module)
    except Exception:
        return None
    return getattr(mod, "__version__", None)


def collect_environment(cfg: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Collect host, interpreter and accelerator facts for provenance."""
    info: Dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    torch_version = _optional_import_version("torch")
    if torch_version is not None:
        info["torch_version"] = torch_version
        try:
            import torch

            info["torch_cuda_version"] = torch.version.cuda
            info["cuda_available"] = bool(torch.cuda.is_available())
            info["cuda_device_count"] = int(torch.cuda.device_count())
            info["cuda_device_names"] = [
                torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
            ]
        except Exception as exc:  # pragma: no cover - defensive
            info["torch_probe_error"] = repr(exc)
    if cfg is not None:
        info["device"] = dict(cfg.get("device", {}))
        info["profile"] = cfg.get("profile")
    return info


@dataclass
class RunManifest:
    """Structured description of a single reproducible run."""

    run_id: str
    profile: str
    config_digest: str
    seed: int
    device: Dict[str, Any]
    output_dir: str
    repo_root: str
    git_commit: Optional[str] = None
    git_dirty: Optional[bool] = None
    git_branch: Optional[str] = None
    model: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def mark_started(self, moment: Optional[datetime] = None) -> None:
        self.started_at = _iso(moment or utc_now())

    def mark_finished(self, moment: Optional[datetime] = None) -> None:
        self.finished_at = _iso(moment or utc_now())

    def duration_seconds(self) -> Optional[float]:
        if not self.started_at or not self.finished_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.finished_at)
        return (end - start).total_seconds()


def build_manifest(
    cfg: Mapping[str, Any],
    output_dir: Path | str,
    repo_root: Optional[Path | str] = None,
    run_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> RunManifest:
    """Build a manifest for a run using ``cfg`` and the enclosing repository."""
    repo = Path(repo_root) if repo_root is not None else Path.cwd()
    git = collect_git_info(repo)
    seed = int(cfg.get("run", {}).get("seed", 0))
    return RunManifest(
        run_id=run_id or new_run_id(str(cfg.get("run", {}).get("run_prefix", "ic"))),
        profile=str(cfg.get("profile", "unknown")),
        config_digest=config_digest(cfg),
        seed=seed,
        device=dict(cfg.get("device", {})),
        output_dir=str(Path(output_dir)),
        repo_root=str(repo),
        git_commit=git.get("git_commit"),
        git_dirty=git.get("git_dirty"),
        git_branch=git.get("git_branch"),
        model=dict(cfg.get("duplexcascade", {})),
        tags=list(tags or cfg.get("run", {}).get("tags", []) or []),
    )


def write_manifest(manifest: RunManifest, path: Path | str) -> Path:
    """Write ``manifest`` to ``path`` (defaults to ``manifest.json`` dir)."""
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest.to_dict(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def write_environment(info: Mapping[str, Any], path: Path | str) -> Path:
    """Write a human-readable ``environment.txt`` snapshot."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in sorted(info.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def manifest_fingerprint(manifest: RunManifest) -> str:
    """Hash the reproducible subset of a manifest (ignores wall-clock time)."""
    reproducible = manifest.to_dict()
    for volatile in ("run_id", "started_at", "finished_at", "output_dir"):
        reproducible.pop(volatile, None)
    payload = json.dumps(reproducible, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
