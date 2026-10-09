"""Unified configuration layer for InterClarify (P0).

The configuration is built from three layers, merged in order:

1. ``configs/base.yaml`` -- shared defaults and the pinned X-Talk source
   reference (repository commit and cluster image);
2. ``configs/<profile>.yaml`` -- one of ``local``, ``replay`` or ``cluster``;
3. runtime overrides -- explicit keyword overrides passed by callers.

The merge is a recursive dict merge that replaces scalars and lists.  The
resolved configuration is hashed (:func:`config_digest`) so that every run
manifest can prove which configuration produced it.

String values support environment expansion with ``${VAR}`` and a default via
``${VAR:-default}``.  This keeps secrets and machine-specific roots out of the
tracked templates while allowing reproducible resolution at run time.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

PROFILES = ("local", "replay", "cluster")
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def default_config_dir() -> Path:
    """Return the repository ``configs/`` directory."""
    return DEFAULT_CONFIG_DIR


def _deep_merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(match: "re.Match[str]") -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else match.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a mapping: {path}")
    return data


def load_config(
    profile: str = "replay",
    config_dir: Optional[Path | str] = None,
    overrides: Optional[Mapping[str, Any]] = None,
    expand_env: bool = True,
) -> Dict[str, Any]:
    """Load and resolve a configuration for ``profile``.

    Parameters
    ----------
    profile:
        One of :data:`PROFILES`.  Raises ``ValueError`` otherwise.
    config_dir:
        Directory holding ``base.yaml`` and ``<profile>.yaml``.  Defaults to
        the repository ``configs/`` directory.
    overrides:
        Optional nested mapping merged on top of the profile.
    expand_env:
        When true (default), expand ``${VAR}`` references in string values.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    cfg_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR

    base = _load_yaml(cfg_dir / "base.yaml")
    prof = _load_yaml(cfg_dir / f"{profile}.yaml")
    cfg = _deep_merge(base, prof)
    cfg["profile"] = profile
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    if expand_env:
        cfg = _expand_env(cfg)
    return cfg


def canonical_json(cfg: Mapping[str, Any]) -> str:
    """Return a stable canonical JSON encoding of ``cfg``."""
    return json.dumps(cfg, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def config_digest(cfg: Mapping[str, Any]) -> str:
    """Return the SHA-256 hex digest of the canonical configuration."""
    return hashlib.sha256(canonical_json(cfg).encode("utf-8")).hexdigest()


def write_resolved_config(cfg: Mapping[str, Any], path: Path | str) -> Path:
    """Write the resolved configuration to ``path`` as YAML."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(dict(cfg), handle, sort_keys=True, allow_unicode=True)
    return path


def resolve_paths(cfg: Mapping[str, Any], repo_root: Optional[Path | str] = None) -> Dict[str, Path]:
    """Resolve configured paths relative to ``repo_root``.

    ``paths.repo_root`` may itself be set by the cluster profile.  Relative
    entries are interpreted against the resolved repository root.
    """
    repo = Path(repo_root) if repo_root is not None else Path.cwd()
    configured_root = cfg.get("paths", {}).get("repo_root", ".")
    if configured_root and configured_root != ".":
        repo = Path(configured_root).expanduser()

    resolved: Dict[str, Path] = {"repo_root": repo}
    for key, value in cfg.get("paths", {}).items():
        if key == "repo_root":
            continue
        candidate = Path(str(value)).expanduser()
        resolved[key] = candidate if candidate.is_absolute() else (repo / candidate)
    return resolved
