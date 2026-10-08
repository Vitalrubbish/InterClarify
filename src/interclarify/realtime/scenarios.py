"""Scripted user-audio scenarios for the P1.2 duplex harness.

A scenario is a deterministic stand-in for a user: a list of audio segments
with scheduling information plus declarative expectations that the runner
later checks against the recorded event stream.  Scenario audio is 24 kHz
mono float32; ``scripts/prepare_p1_2_scenarios.py`` synthesizes the speech
files through the pinned Kyutai TTS service, while silence segments are pure
zeros generated in memory (no file needed).

The scenario file (default ``configs/p1_2_scenarios.json``) is tracked in Git;
the derived audio lives under a configurable root (git-ignored ``*.wav``).
The loader is strict so a stale or partial asset directory fails fast with an
explicit message instead of producing a confusing run.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import soundfile as sf

# Expectation keys understood by ``scripts/run_p1_2_live_link.py``.
KNOWN_EXPECT_KEYS = {
    "answer_expected": bool,
    "backchannel_expected": bool,
    "barge_in_stop_expected": bool,
    "expect_no_asr": bool,
    "user_asr_contains": str,
    "assistant_contains": str,
    "min_tts_played_seconds": (int, float),
}

# Start-condition keys understood by the client send loop.
KNOWN_START_CONDITION_KEYS = {"tts_played_min_seconds"}


@dataclass
class Segment:
    """One stretch of scripted user audio.

    ``audio`` is a wav path relative to the scenario audio root; ``None``
    means digital silence, in which case ``duration_seconds`` is required.
    ``start_seconds`` schedules the segment relative to scenario start;
    alternatively ``start_condition`` delays it until the playback owner has
    played at least ``tts_played_min_seconds`` of TTS audio (used to land a
    barge-in mid-answer regardless of model latency).
    """

    label: str
    audio: Optional[Path] = None
    start_seconds: float = 0.0
    duration_seconds: Optional[float] = None
    start_condition: Optional[Dict[str, float]] = None
    synth_text: Optional[str] = None  # provenance for the TTS prep script


@dataclass
class Scenario:
    """A named scripted session with declarative expectations."""

    name: str
    description: str
    segments: List[Segment]
    expect: Dict[str, Any] = field(default_factory=dict)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"invalid scenario file: {message}")


def load_scenarios(path: Path | str, audio_root: Path | str) -> List[Scenario]:
    """Parse and validate the scenario file against ``audio_root``.

    Raises ``ValueError`` with the concrete problem on any structural issue
    and ``FileNotFoundError`` listing every missing audio file.
    """
    path = Path(path)
    audio_root = Path(audio_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    _check(isinstance(payload, dict), "top level must be an object")
    raw_scenarios = payload.get("scenarios")
    _check(isinstance(raw_scenarios, list) and raw_scenarios, "'scenarios' must be a non-empty list")

    scenarios: List[Scenario] = []
    names: set[str] = set()
    missing: List[str] = []
    for index, raw in enumerate(raw_scenarios):
        _check(isinstance(raw, dict), f"scenarios[{index}] must be an object")
        name = raw.get("name")
        _check(isinstance(name, str) and name, f"scenarios[{index}].name must be a non-empty string")
        _check(name not in names, f"duplicate scenario name {name!r}")
        names.add(name)
        description = str(raw.get("description", ""))
        raw_segments = raw.get("segments")
        _check(isinstance(raw_segments, list) and raw_segments, f"scenario {name!r} needs at least one segment")

        segments: List[Segment] = []
        for s_index, raw_seg in enumerate(raw_segments):
            where = f"scenario {name!r} segment {s_index}"
            _check(isinstance(raw_seg, dict), f"{where} must be an object")
            label = raw_seg.get("label")
            _check(isinstance(label, str) and label, f"{where}.label must be a non-empty string")
            start_seconds = float(raw_seg.get("start_seconds", 0.0))
            _check(start_seconds >= 0, f"{where}.start_seconds must be >= 0")
            duration = raw_seg.get("duration_seconds")
            if duration is not None:
                duration = float(duration)
                _check(duration > 0, f"{where}.duration_seconds must be > 0")
            audio_rel = raw_seg.get("audio")
            audio_path: Optional[Path] = None
            if audio_rel is not None:
                _check(isinstance(audio_rel, str) and audio_rel, f"{where}.audio must be a string or null")
                audio_path = audio_root / audio_rel
                if not audio_path.is_file():
                    missing.append(str(audio_path))
            else:
                _check(duration is not None, f"{where} has audio=null and needs duration_seconds")
            condition = raw_seg.get("start_condition")
            if condition is not None:
                _check(isinstance(condition, dict), f"{where}.start_condition must be an object")
                _check(
                    set(condition) <= KNOWN_START_CONDITION_KEYS,
                    f"{where}.start_condition has unknown keys {sorted(set(condition) - KNOWN_START_CONDITION_KEYS)}",
                )
                _check(
                    float(condition.get("tts_played_min_seconds", -1.0)) >= 0,
                    f"{where}.start_condition.tts_played_min_seconds must be >= 0",
                )
            segments.append(
                Segment(
                    label=label,
                    audio=audio_path,
                    start_seconds=start_seconds,
                    duration_seconds=duration,
                    start_condition=condition,
                    synth_text=(str(raw_seg["synth_text"]) if raw_seg.get("synth_text") else None),
                )
            )

        expect = raw.get("expect", {})
        _check(isinstance(expect, dict), f"scenario {name!r}.expect must be an object")
        for key, value in expect.items():
            _check(key in KNOWN_EXPECT_KEYS, f"scenario {name!r}.expect has unknown key {key!r}")
            expected_type = KNOWN_EXPECT_KEYS[key]
            _check(isinstance(value, expected_type), f"scenario {name!r}.expect.{key} has wrong type")
        scenarios.append(Scenario(name=name, description=description, segments=segments, expect=dict(expect)))

    if missing:
        listing = "\n  ".join(missing)
        raise FileNotFoundError(
            f"{len(missing)} scenario audio file(s) missing; run scripts/prepare_p1_2_scenarios.py first:\n  {listing}"
        )
    return scenarios


def load_audio_mono(path: Path | str, sample_rate: int) -> np.ndarray:
    """Read an audio file as mono float32 at ``sample_rate`` (polyphase resample)."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if int(sr) == int(sample_rate):
        return np.ascontiguousarray(mono, dtype=np.float32)
    from scipy.signal import resample_poly

    gcd = math.gcd(int(sr), int(sample_rate))
    converted = resample_poly(mono, int(sample_rate) // gcd, int(sr) // gcd)
    return np.ascontiguousarray(converted, dtype=np.float32)


def materialize_segment(segment: Segment, sample_rate: int) -> np.ndarray:
    """Return the exact samples the client should send for ``segment``.

    Applies duration truncation/padding (with zeros) so the scheduling
    contract of the segment holds even if a source file is shorter.
    """
    if segment.audio is None:
        duration = segment.duration_seconds or 0.0
        return np.zeros(int(round(duration * sample_rate)), dtype=np.float32)
    pcm = load_audio_mono(segment.audio, sample_rate)
    if segment.duration_seconds is not None:
        target = int(round(segment.duration_seconds * sample_rate))
        if pcm.size < target:
            pcm = np.concatenate([pcm, np.zeros(target - pcm.size, dtype=np.float32)])
        else:
            pcm = pcm[:target]
    return pcm


def audio_digest(path: Path | str) -> str:
    """SHA-256 of a scenario audio file, for run provenance."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scenario_audio_digests(scenarios: List[Scenario]) -> Dict[str, str]:
    """Map every referenced audio file (as resolved by the loader) to its digest."""
    digests: Dict[str, str] = {}
    for scenario in scenarios:
        for segment in scenario.segments:
            if segment.audio is not None:
                digests.setdefault(str(segment.audio), audio_digest(segment.audio))
    return digests
