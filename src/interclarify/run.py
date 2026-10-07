"""Minimal run context and structured run log for InterClarify (P0).

This module is the P0 bootstrap for the experiment bookkeeping required by
``docs/engineering_implementation.md`` section 12.  It creates a unique run
directory containing:

``manifest.json``
    the :class:`~interclarify.manifest.RunManifest`;
``resolved_config.yaml``
    the fully merged configuration actually used;
``environment.txt``
    host, interpreter, dependency and accelerator snapshot;
``events.jsonl``
    append-only structured control events (``seq``, monotonic and wall time);
``metrics.json``
    optional summary metrics written by the caller.

The event stream here records run *lifecycle* events only.  The runtime
``EventRecorder`` for ASR/LLM/TTS/playback events is introduced in phase P1.3
and will reuse the same on-disk format.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, TextIO

from .config import load_config, resolve_paths, write_resolved_config
from .manifest import (
    RunManifest,
    build_manifest,
    collect_environment,
    new_run_id,
    utc_now,
    write_environment,
    write_manifest,
)

EVENTS_FILENAME = "events.jsonl"
METRICS_FILENAME = "metrics.json"
RESOLVED_CONFIG_FILENAME = "resolved_config.yaml"


@dataclass
class RunContext:
    """Owns a run directory and its append-only structured log."""

    run_id: str
    run_dir: Path
    config: Dict[str, Any]
    manifest: RunManifest
    _events_handle: Optional[TextIO] = field(default=None, repr=False)
    _event_seq: int = field(default=0, repr=False)
    _monotonic_origin: float = field(default_factory=time.monotonic, repr=False)

    # -- construction -----------------------------------------------------
    @classmethod
    def create(
        cls,
        output_root: Optional[Path | str] = None,
        profile: str = "replay",
        config_dir: Optional[Path | str] = None,
        overrides: Optional[Mapping[str, Any]] = None,
        repo_root: Optional[Path | str] = None,
        run_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> "RunContext":
        cfg = load_config(profile=profile, config_dir=config_dir, overrides=overrides)
        paths = resolve_paths(cfg, repo_root=repo_root)
        root = Path(output_root) if output_root is not None else paths["repo_root"] / cfg.get(
            "run", {}
        ).get("output_root", "experiments")
        run_id = run_id or new_run_id(str(cfg.get("run", {}).get("run_prefix", "ic")))
        run_dir = Path(root) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest = build_manifest(cfg, run_dir, repo_root=paths["repo_root"], run_id=run_id, tags=tags)
        manifest.environment = collect_environment(cfg)
        manifest.mark_started()

        write_manifest(manifest, run_dir / "manifest.json")
        write_resolved_config(cfg, run_dir / RESOLVED_CONFIG_FILENAME)
        write_environment(manifest.environment, run_dir / "environment.txt")

        ctx = cls(run_id=run_id, run_dir=run_dir, config=cfg, manifest=manifest)
        ctx._events_handle = (run_dir / EVENTS_FILENAME).open("a", encoding="utf-8")
        ctx.record("run_start", profile=profile, config_digest=manifest.config_digest)
        return ctx

    # -- events -----------------------------------------------------------
    def record(self, event_type: str, **payload: Any) -> Dict[str, Any]:
        """Append a structured event and return the recorded dict."""
        self._event_seq += 1
        event = {
            "seq": self._event_seq,
            "event_type": event_type,
            "monotonic_ms": round((time.monotonic() - self._monotonic_origin) * 1000.0, 3),
            "wall_time": utc_now().isoformat(),
            "run_id": self.run_id,
            "session_id": self.config.get("run", {}).get("session_id"),
        }
        if payload:
            event["payload"] = payload
        if self._events_handle is not None:
            self._events_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._events_handle.flush()
        return event

    @property
    def events_path(self) -> Path:
        return self.run_dir / EVENTS_FILENAME

    # -- metrics / teardown ----------------------------------------------
    def write_metrics(self, metrics: Mapping[str, Any]) -> Path:
        path = self.run_dir / METRICS_FILENAME
        path.write_text(json.dumps(dict(metrics), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def finalize(self, metrics: Optional[Mapping[str, Any]] = None) -> None:
        if metrics is not None:
            self.write_metrics(metrics)
        self.manifest.mark_finished()
        write_manifest(self.manifest, self.run_dir / "manifest.json")
        self.record("run_end", duration_s=self.manifest.duration_seconds())

    def close(self) -> None:
        if self._events_handle is not None:
            self._events_handle.close()
            self._events_handle = None

    def __enter__(self) -> "RunContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
