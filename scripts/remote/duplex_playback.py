"""Record real-time assistant playback with request cancellation and bounded buffering."""
from __future__ import annotations

from collections import deque
import json
import threading
import time


class CancellablePlayer:
    def __init__(self, started, record, committed, completed, sample_rate=16000, output=None):
        self.started, self.record = started, record
        self.committed, self.completed = committed, completed
        self.sample_rate = sample_rate
        self.condition = threading.Condition()
        self.queue = deque()
        self.frames = []
        self.reply_frames = []
        self.completed_text = []
        self.committed_samples = 0
        self.reply_samples = 0
        self.timeline_end_sample = 0
        self.sink = self.journal = None
        if output is not None:
            import soundfile as sf

            self.sink = sf.SoundFile(str(output / "output.wav"), mode="w", samplerate=sample_rate,
                                     channels=1, subtype="PCM_16")
            self.journal = (output / "playback_frames.jsonl").open("x")
        self.identifier = None
        self.reply_identifier = None
        self.cancel_event = threading.Event()
        self.production_complete = False
        self.in_frame = False
        self.closed = False
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def begin(self, identifier):
        with self.condition:
            if self.identifier is not None:
                raise RuntimeError("Cancel or complete the previous playback request first")
            self.identifier = identifier
            self.reply_identifier = identifier
            self.cancel_event = threading.Event()
            self.production_complete = False
            self.reply_frames = []
            self.completed_text = []
            self.committed_samples = self.reply_samples = 0
            self.condition.notify_all()

    def enqueue(self, identifier, audio, text):
        import numpy as np

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all() or len(audio) > 30 * self.sample_rate:
            raise ValueError("Invalid or oversized playback segment")
        deadline = time.monotonic() + 35
        with self.condition:
            while len(self.queue) >= 2 and self.identifier == identifier and not self.closed:
                if time.monotonic() > deadline:
                    raise TimeoutError("Playback queue stayed full")
                self.condition.wait(timeout=0.1)
            if self.closed or self.identifier != identifier or self.cancel_event.is_set():
                self.record("late_audio_discarded", request_id=identifier)
                return False
            self.queue.append((identifier, audio.copy(), text, self.cancel_event))
            self.record("audio_queued", request_id=identifier, samples=len(audio), queue_depth=len(self.queue))
            self.condition.notify_all()
            return True

    def finish_production(self, identifier):
        with self.condition:
            if self.identifier == identifier:
                self.production_complete = True
                self.condition.notify_all()

    def cancel(self, identifier):
        import numpy as np

        with self.condition:
            if self.reply_identifier != identifier:
                return {"tail": np.zeros(0, dtype=np.float32), "text": "", "played_samples": 0,
                        "committed_samples": 0}
            self.cancel_event.set()
            self.queue.clear()
            deadline = time.monotonic() + 1
            while self.in_frame:
                if time.monotonic() > deadline:
                    raise TimeoutError("Player did not stop within one second")
                self.condition.wait(timeout=0.01)
            self.identifier = None
            played = np.concatenate(self.reply_frames) if self.reply_frames else np.zeros(0, dtype=np.float32)
            self.record("playback_cancelled", request_id=identifier, played_samples=len(played), queue_depth=0)
            self.condition.notify_all()
            return {"tail": played[self.committed_samples:], "text": " ".join(self.completed_text),
                    "played_samples": len(played), "committed_samples": self.committed_samples}

    def _capture(self, start, samples, identifier):
        import numpy as np

        offset = round(start * self.sample_rate)
        if offset < 0 or offset + len(samples) > 180 * self.sample_rate:
            raise ValueError("Live recording exceeds the sample timeline budget")
        if self.sink is not None:
            if offset < self.sink.tell():
                raise ValueError("Playback frames overlap on the live recording clock")
            gap = offset - self.sink.tell()
            if gap:
                self.sink.write(np.zeros(gap, dtype=np.float32))
            self.sink.write(samples)
            self.sink.flush()
            self.journal.write(json.dumps({"request_id": identifier, "start_sample": offset,
                                           "samples": len(samples), "time": start}) + "\n")
            self.journal.flush()
        self.frames.append((start, samples, identifier))
        self.timeline_end_sample = offset + len(samples)

    def _wait_until(self, deadline, cancelled):
        while not cancelled.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            cancelled.wait(remaining)
        return True

    def _run(self):
        try:
            while True:
                finished = None
                with self.condition:
                    while not self.queue and not self.closed:
                        if self.identifier is not None and self.production_complete:
                            finished = self.identifier
                            self.identifier = None
                            break
                        self.condition.wait(timeout=0.1)
                    if self.closed:
                        return
                    if finished is None:
                        identifier, audio, text, cancelled = self.queue.popleft()
                        self.condition.notify_all()
                if finished is not None:
                    self.record("playback_complete", request_id=finished)
                    self.completed(finished)
                    continue
                fully_played = True
                size = self.sample_rate // 50
                for offset in range(0, len(audio), size):
                    with self.condition:
                        if self.identifier != identifier or cancelled.is_set() or self.closed:
                            fully_played = False
                            break
                        self.in_frame = True
                    if offset == 0:
                        self.record("playback_segment_start", request_id=identifier, samples=len(audio))
                    frame = audio[offset:offset + size]
                    # Enforce the audio sample clock before starting the next physical interval.
                    if self._wait_until(self.started + self.timeline_end_sample / self.sample_rate, cancelled):
                        with self.condition:
                            self.in_frame = False
                            self.condition.notify_all()
                        fully_played = False
                        break
                    began = time.monotonic()
                    interrupted = self._wait_until(began + len(frame) / self.sample_rate, cancelled)
                    count = min(len(frame), int((time.monotonic() - began) * self.sample_rate)) if interrupted else len(frame)
                    with self.condition:
                        if count:
                            samples = frame[:count].copy()
                            self._capture(began - self.started, samples, identifier)
                            self.reply_frames.append(samples)
                            self.reply_samples += count
                        if offset + len(frame) == len(audio) and count == len(frame):
                            self.completed_text.append(text)
                            self.committed_samples = self.reply_samples
                        self.in_frame = False
                        self.condition.notify_all()
                    if interrupted:
                        fully_played = False
                        break
                if fully_played:
                    self.record("playback_segment_end", request_id=identifier, text=text)
                    self.committed(identifier, text)
        except BaseException as exc:
            self.error = exc
            with self.condition:
                self.in_frame = False
                self.condition.notify_all()

    def close(self, minimum_seconds=0):
        import numpy as np

        with self.condition:
            self.closed = True
            self.cancel_event.set()
            self.condition.notify_all()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("Playback thread did not terminate")
        if self.sink is not None:
            try:
                minimum = round(minimum_seconds * self.sample_rate)
                if minimum > 180 * self.sample_rate:
                    raise ValueError("Recording padding exceeds the timeline budget")
                if minimum > self.sink.tell():
                    self.sink.write(np.zeros(minimum - self.sink.tell(), dtype=np.float32))
            finally:
                self.sink.close()
                self.journal.close()
                self.sink = self.journal = None
        if self.error:
            raise RuntimeError(f"Playback thread failed: {self.error}") from self.error

    def render(self, minimum_seconds=0):
        import numpy as np

        if self.thread.is_alive():
            raise RuntimeError("Stop the player before rendering the final timeline")
        length = max([int(minimum_seconds * self.sample_rate),
                      *[round(start * self.sample_rate) + len(audio) for start, audio, _ in self.frames]])
        if length > 180 * self.sample_rate:
            raise ValueError("Output timeline exceeds the 180 second sample budget")
        output = np.zeros(length, dtype=np.float32)
        for start, audio, _ in self.frames:
            offset = round(start * self.sample_rate)
            output[offset:offset + len(audio)] += audio
        return np.clip(output, -1.0, 1.0)
