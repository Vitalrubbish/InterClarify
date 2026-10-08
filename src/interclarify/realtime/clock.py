"""Pacing clocks for the P1.2 duplex harness.

Two clocks are provided:

- :class:`RealClock` -- wall-clock pacing for live runs.  Playback and idle
  waits advance at real time, so full-duplex evidence such as "user frames
  sent while the system was speaking" is measured against real overlap.
- :class:`VirtualClock` -- a manually advanced clock for fast control-path
  checks (e.g. CPU-only tests against a stub server).  ``sleep`` advances
  virtual time instantly and returns immediately.

Service-facing pacing is always real time regardless of the clock: the
official server consumes microphone audio as a real-time 24 kHz stream, so the
client sends audio frames with wall-clock spacing in every mode.  The clock
only governs the local playback owner and idle waits (see
``docs/engineering_implementation.md`` section 5.4: pre-recorded audio plus a
virtual playback clock when the live device link is unavailable).
"""

from __future__ import annotations

import time


class Clock:
    """Monotonic clock interface used by the harness (seconds, float)."""

    def now(self) -> float:
        """Return the current clock reading in seconds."""
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        """Block (or fast-forward) until ``seconds`` have elapsed on this clock."""
        raise NotImplementedError

    def sleep_until(self, deadline: float) -> None:
        """Sleep until :meth:`now` reaches ``deadline`` (no-op if already past)."""
        remaining = deadline - self.now()
        if remaining > 0:
            self.sleep(remaining)


class RealClock(Clock):
    """Wall-clock pacing backed by :func:`time.monotonic` / :func:`time.sleep`."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class VirtualClock(Clock):
    """Manually advanced clock; sleeps fast-forward virtual time instantly.

    The clock starts at ``origin`` (default 0.0).  Because nothing blocks,
    callers drive time explicitly either through :meth:`sleep` /
    :meth:`sleep_until` or by advancing the clock with :meth:`advance`.
    """

    def __init__(self, origin: float = 0.0) -> None:
        self._now = float(origin)

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward by ``seconds`` without sleeping."""
        if seconds < 0:
            raise ValueError("cannot advance a virtual clock backwards")
        self._now += float(seconds)

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot sleep for a negative duration")
        self._now += float(seconds)


def make_clock(mode: str) -> Clock:
    """Build a clock from the ``clock.mode`` configuration value."""
    if mode == "real":
        return RealClock()
    if mode == "virtual":
        return VirtualClock()
    raise ValueError(f"unknown clock mode {mode!r}; expected 'real' or 'virtual'")
