"""Playback owners for the P1.2 duplex harness.

There is exactly one playback owner per session: every TTS audio frame received
from the official server is committed to a single sink, and only that sink may
decide what has actually been heard.  This mirrors the project constraint that
already-played audio is irrevocable -- :meth:`PlaybackSink.stop` cancels only
the committed-but-unplayed tail, never the played head (``docs/
engineering_implementation.md`` section 2.2).

Two sinks are provided:

- :class:`VirtualPlaybackSink` -- headless owner used on the cluster and in
  tests.  It drains at the clock's pace, records what *would* have been heard
  (played head) into a raw float32 file for review, and reports cancelled
  samples on stop.
- :class:`SoundDevicePlaybackSink` -- local-machine owner that plays through
  PortAudio (``sounddevice``).  The same commit/stop bookkeeping applies.

Both sinks emit structured events through the injected ``emit`` callable:
``playback_started``, ``playback_finished`` (natural drain) and
``playback_stopped`` (cancelled), each carrying played/committed/cancelled
sample counts so runs can distinguish *committed TTS* from *played audio*.
"""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .clock import Clock

EmitFn = Callable[..., None]


class PlaybackSink:
    """Single-owner TTS playback interface (24 kHz mono float32)."""

    def __init__(self, sample_rate: int, emit: EmitFn) -> None:
        self.sample_rate = int(sample_rate)
        self._emit = emit
        self.committed_samples = 0
        self.cancelled_samples = 0
        self.max_backlog_samples = 0

    # -- producer side ----------------------------------------------------
    def commit(self, pcm: np.ndarray) -> None:
        """Commit a new TTS frame for playback (server -> owner hand-off)."""
        raise NotImplementedError

    # -- observer side ------------------------------------------------------
    def is_speaking(self) -> bool:
        """True while committed audio remains unheard."""
        raise NotImplementedError

    @property
    def played_samples(self) -> int:
        raise NotImplementedError

    @property
    def pending_samples(self) -> int:
        raise NotImplementedError

    def played_seconds(self) -> float:
        return self.played_samples / float(self.sample_rate)

    def pending_seconds(self) -> float:
        return self.pending_samples / float(self.sample_rate)

    # -- control side -------------------------------------------------------
    def stop(self, reason: str = "") -> int:
        """Cancel the unplayed tail; return the number of cancelled samples."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    # -- helpers ------------------------------------------------------------
    def _check_backlog(self) -> None:
        self.max_backlog_samples = max(self.max_backlog_samples, self.pending_samples)


class VirtualPlaybackSink(PlaybackSink):
    """Headless playback owner draining at the pace of the given clock.

    Parameters
    ----------
    sample_rate:
        Audio sample rate (24000 for the official pipeline).
    clock:
        Pacing clock; with a :class:`~interclarify.realtime.clock.RealClock`
        the playhead advances in real time, with a ``VirtualClock`` it advances
        whenever virtual time moves.
    emit:
        Event callback receiving ``playback_started`` / ``playback_finished``
        / ``playback_stopped`` plus sample-count payloads.
    played_path:
        Optional raw float32 (headerless, little-endian) file that receives
        exactly the played head, so reviewers can listen to what was audible.
    """

    def __init__(
        self,
        sample_rate: int,
        clock: Clock,
        emit: EmitFn,
        played_path: Optional[Path | str] = None,
    ) -> None:
        super().__init__(sample_rate, emit)
        self._clock = clock
        self._pending: deque[np.ndarray] = deque()
        self._pending_count = 0
        self._played_count = 0
        self._last_advance = clock.now()
        self._speaking = False
        self._played_path: Optional[Path] = None
        self._played_handle = None
        self.set_played_path(played_path)

    # -- played-head capture --------------------------------------------------
    def set_played_path(self, played_path: Optional[Path | str]) -> None:
        """Switch the played-head capture file (``None`` disables capture)."""
        if self._played_handle is not None:
            self._played_handle.close()
            self._played_handle = None
        self._played_path = Path(played_path) if played_path else None

    def _write_played(self, chunk: np.ndarray) -> None:
        if self._played_path is None or chunk.size == 0:
            return
        if self._played_handle is None:
            self._played_path.parent.mkdir(parents=True, exist_ok=True)
            self._played_handle = self._played_path.open("wb")
        self._played_handle.write(np.asarray(chunk, dtype="<f4").tobytes())

    # -- PlaybackSink API ---------------------------------------------------
    def commit(self, pcm: np.ndarray) -> None:
        self._advance()
        frame = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if frame.size == 0:
            return
        self._pending.append(frame)
        self._pending_count += int(frame.size)
        self.committed_samples += int(frame.size)
        if not self._speaking:
            self._speaking = True
            self._emit(
                "playback_started",
                sample_rate=self.sample_rate,
                committed_samples=self.committed_samples,
                pending_samples=self._pending_count,
            )
        self._check_backlog()

    @property
    def played_samples(self) -> int:
        self._advance()
        return self._played_count

    @property
    def pending_samples(self) -> int:
        self._advance()
        return self._pending_count

    def is_speaking(self) -> bool:
        self._advance()
        return self._speaking

    def stop(self, reason: str = "") -> int:
        self._advance()
        cancelled = self._pending_count
        if cancelled:
            self._pending.clear()
            self._pending_count = 0
            self.cancelled_samples += cancelled
        if self._speaking:
            self._speaking = False
            self._emit(
                "playback_stopped",
                reason=reason,
                cancelled_samples=cancelled,
                played_samples=self._played_count,
                committed_samples=self.committed_samples,
            )
        return cancelled

    def close(self) -> None:
        if self._played_handle is not None:
            self._played_handle.close()
            self._played_handle = None

    # -- internals -----------------------------------------------------------
    def _advance(self) -> None:
        now = self._clock.now()
        elapsed = now - self._last_advance
        self._last_advance = now
        if elapsed <= 0 or self._pending_count == 0:
            return
        n = min(self._pending_count, int(round(elapsed * self.sample_rate)))
        if n <= 0:
            return
        played_chunks: list[np.ndarray] = []
        remaining = n
        while remaining > 0 and self._pending:
            head = self._pending[0]
            if head.size <= remaining:
                played_chunks.append(self._pending.popleft())
                remaining -= int(head.size)
            else:
                played_chunks.append(head[:remaining].copy())
                self._pending[0] = head[remaining:]
                remaining = 0
        self._pending_count -= n
        self._played_count += n
        self._write_played(np.concatenate(played_chunks))
        if self._pending_count == 0 and self._speaking:
            self._speaking = False
            self._emit(
                "playback_finished",
                played_samples=self._played_count,
                committed_samples=self.committed_samples,
            )


class SoundDevicePlaybackSink(PlaybackSink):
    """Local-machine playback owner backed by PortAudio (``sounddevice``).

    The stream callback renders committed frames and only counts the rendered
    portion as played; :meth:`stop` drops everything not yet rendered, which
    is exactly the barge-in "cancel unplayed audio" path of the browser demo
    (``web/client.js`` clears the play queue on ``audio_control: stop``).

    ``sounddevice`` is imported lazily so headless machines without PortAudio
    can still import this module.
    """

    def __init__(
        self,
        sample_rate: int,
        emit: EmitFn,
        device: Optional[str | int] = None,
        blocksize: int = 1920,
    ) -> None:
        super().__init__(sample_rate, emit)
        import sounddevice as sd  # lazy: requires the PortAudio system library

        self._sd = sd
        self._lock = threading.Lock()
        self._pending: deque[np.ndarray] = deque()
        self._pending_count = 0
        self._played_count = 0
        self._drained = True
        self._closed = False

        def _callback(outdata, frames, time_info, status) -> None:  # noqa: ANN001
            del time_info, status
            rendered = np.zeros(frames, dtype=np.float32)
            filled = 0
            with self._lock:
                while filled < frames and self._pending:
                    head = self._pending[0]
                    take = min(frames - filled, head.size)
                    rendered[filled : filled + take] = head[:take]
                    if take == head.size:
                        self._pending.popleft()
                    else:
                        self._pending[0] = head[take:]
                    filled += take
                self._pending_count -= filled
                self._played_count += filled
                if self._pending_count == 0:
                    self._drained = True
            outdata[:] = rendered.reshape(-1, 1)

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=int(blocksize),
            device=device,
            callback=_callback,
        )
        self._stream.start()

    def commit(self, pcm: np.ndarray) -> None:
        frame = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if frame.size == 0 or self._closed:
            return
        with self._lock:
            restarted = self._drained
            self._pending.append(frame)
            self._pending_count += int(frame.size)
            self._drained = False
            self.committed_samples += int(frame.size)
            pending = self._pending_count
        self._check_backlog()
        if restarted:
            self._emit(
                "playback_started",
                sample_rate=self.sample_rate,
                committed_samples=self.committed_samples,
                pending_samples=pending,
            )

    @property
    def played_samples(self) -> int:
        with self._lock:
            return self._played_count

    @property
    def pending_samples(self) -> int:
        with self._lock:
            return self._pending_count

    def is_speaking(self) -> bool:
        with self._lock:
            return not self._drained

    def stop(self, reason: str = "") -> int:
        with self._lock:
            cancelled = self._pending_count
            if cancelled:
                self._pending.clear()
                self._pending_count = 0
                self.cancelled_samples += cancelled
            was_speaking = not self._drained
            self._drained = True
            played = self._played_count
        if was_speaking:
            self._emit(
                "playback_stopped",
                reason=reason,
                cancelled_samples=cancelled,
                played_samples=played,
                committed_samples=self.committed_samples,
            )
        return cancelled

    def close(self) -> None:
        self._closed = True
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
