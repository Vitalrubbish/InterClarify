"""Coordinate bounded live generation, playback and versioned audible history."""
from __future__ import annotations

from collections import deque
import re
import threading
import time

from duplex_playback import CancellablePlayer
from generation_worker import request, request_stream


SYSTEM_PROMPT = "You are a helpful voice assistant. Reply naturally in English in two or three concise sentences."


def take_segment(text, final=False, max_characters=240):
    boundary = re.search(r"[.!?](?:\s+|$)", text)
    if boundary and boundary.end() <= max_characters:
        end = boundary.end()
    elif len(text) > max_characters:
        end = text.rfind(" ", 0, max_characters + 1)
        end = end if end > 0 else max_characters
    elif final:
        end = len(text)
    else:
        return None, text
    return text[:end].strip(), text[end:]


def sentences(text, max_characters=240, first_characters=None):
    result = []
    while text:
        limit = first_characters if not result and first_characters is not None else max_characters
        segment, text = take_segment(text, final=True, max_characters=limit)
        if segment:
            result.append(segment)
    return result


class ReplySession:
    def __init__(self, started, record, recognize, qwen_socket, tts_socket, tag, seed=42, output=None,
                 segment_characters=40, first_segment_characters=20):
        if not 20 <= segment_characters <= 240:
            raise ValueError("TTS segment limit must be between 20 and 240 characters")
        self.segment_characters = segment_characters
        self.first_segment_characters = first_segment_characters or segment_characters
        if not 20 <= self.first_segment_characters <= segment_characters:
            raise ValueError("First TTS segment must be between 20 characters and the normal segment limit")
        self.record, self.recognize = record, recognize
        self.qwen_socket, self.tts_socket = qwen_socket, tts_socket
        self.tag, self.seed = tag, seed
        self.lock = threading.RLock()
        self.history, self.errors = [], []
        self.current, self.pending = None, None
        self.counter = 0
        self.closed = False
        self.condition = threading.Condition(self.lock)
        self.tts_jobs, self.cancel_jobs, self.history_jobs = deque(), deque(), deque()
        self.player = CancellablePlayer(started, record, self._committed, self._completed, output=output)
        self.worker = threading.Thread(target=self._run_generation, daemon=True)
        self.tts_worker = threading.Thread(target=self._run_tts, daemon=True)
        self.cancel_worker = threading.Thread(target=self._run_cleanup, args=(False,), daemon=True)
        self.history_worker = threading.Thread(target=self._run_cleanup, args=(True,), daemon=True)
        self.workers = [self.worker, self.tts_worker, self.cancel_worker, self.history_worker]
        for worker in self.workers:
            worker.start()

    def busy(self):
        with self.lock:
            return self.current is not None

    def speaking(self):
        with self.lock:
            if self.current is None:
                return False
            with self.player.condition:
                return (self.player.reply_identifier == self.current["id"]
                        and self.player.reply_samples > 0 and not self.current["cancel"].is_set())

    def snapshot(self, user_text=""):
        with self.lock:
            messages = []
            for message in self.history:
                content = message["content"].strip()
                if not content:
                    continue
                if messages and messages[-1]["role"] == message["role"]:
                    messages[-1]["content"] += " " + content
                else:
                    messages.append({"role": message["role"], "content": content})
            if self.current and self.current["spoken_text"].strip():
                messages.append({"role": "assistant", "content": self.current["spoken_text"].strip()})
            if user_text.strip():
                if messages and messages[-1]["role"] == "user":
                    messages[-1]["content"] += " " + user_text.strip()
                else:
                    messages.append({"role": "user", "content": user_text.strip()})
            return messages

    def _committed(self, identifier, text):
        with self.lock:
            if self.current and self.current["id"] == identifier and not self.current["cancel"].is_set():
                self.current["spoken_text"] += " " + text
                self.record("assistant_text_visible", request_id=identifier,
                            text=self.current["spoken_text"].strip(), source="fully_played_sentences")

    def _finalize(self, keep_empty=False):
        current = self.current
        if current and (keep_empty or current["spoken_text"].strip()):
            entry = {"role": "assistant", "content": current["spoken_text"].strip()}
            self.history.append(entry)
            current["history_entry"] = entry
        self.current = None

    def _completed(self, identifier):
        with self.lock:
            if self.current and self.current["id"] == identifier and not self.current["cancel"].is_set():
                self._finalize()

    def start(self, text):
        if not text.strip():
            self.record("empty_start_ignored")
            return False
        with self.condition:
            if self.closed:
                raise RuntimeError("Reply session is closed")
            if self.current is not None:
                self.record("duplicate_start_ignored", request_id=self.current["id"])
                return False
            self.counter += 1
            identifier = f"{self.tag}-r{self.counter}"
            if self.history and self.history[-1]["role"] == "user":
                self.history[-1]["content"] += " " + text.strip()
            else:
                self.history.append({"role": "user", "content": text.strip()})
            current = {"id": identifier, "cancel": threading.Event(), "spoken_text": "", "tts_id": None,
                       "seed": self.seed + self.counter - 1, "history_version": 0}
            self.current = current
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.snapshot()]
            self.player.begin(identifier)
            self.record("reply_started", request_id=identifier, user_text=text,
                        generation_state_mapping="speaking_until_playback_complete")
            self.pending = (current, messages)
            self.condition.notify_all()
        return True

    def _failure(self, current, exc):
        with self.condition:
            self.record("generation_failure", request_id=current["id"], error=f"{type(exc).__name__}: {exc}")
            if not current["cancel"].is_set():
                self.errors.append(exc)
            self.condition.notify_all()

    def _run_generation(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                current, messages = self.pending
                self.pending = None
            if not current["cancel"].is_set():
                self.record("generation_dispatched", request_id=current["id"])
                self._generate(current, messages)

    def _queue_tts(self, current, index, text):
        deadline = time.monotonic() + 90
        with self.condition:
            while len(self.tts_jobs) >= 2 and not self.closed and not current["cancel"].is_set():
                if time.monotonic() > deadline:
                    raise TimeoutError("TTS queue stayed full")
                self.condition.wait(timeout=0.1)
            if self.closed or current["cancel"].is_set():
                return False
            self.tts_jobs.append((current, index, text))
            self.record("tts_segment_ready", request_id=current["id"], segment_index=index,
                        text=text, queue_depth=len(self.tts_jobs), end_of_text=text is None)
            self.condition.notify_all()
            return True

    def _generate(self, current, messages):
        identifier = current["id"]
        pending, full, index = "", "", 0
        try:
            self.record("llm_request", request_id=identifier, messages=messages)
            for event in request_stream(self.qwen_socket, {"id": identifier, "messages": messages,
                                        "seed": current["seed"], "max_new_tokens": 128}):
                if current["cancel"].is_set():
                    return
                if event["event"] == "done":
                    self.record("llm_result", request_id=identifier, response=event,
                                visibility="generation_only_until_played")
                    if event.get("cancelled"):
                        return
                    if not full.strip():
                        raise ValueError("LLM returned empty text")
                    final = True
                else:
                    delta = event["text"]
                    if not full:
                        self.record("llm_first_text", request_id=identifier)
                    full += delta
                    pending += delta
                    final = False
                    self.record("llm_text_delta", request_id=identifier, text=delta,
                                visibility="generation_only_until_played")
                while pending:
                    limit = self.first_segment_characters if index == 0 else self.segment_characters
                    segment, remaining = take_segment(pending, final=final, max_characters=limit)
                    if segment is None:
                        break
                    pending = remaining
                    if segment:
                        if not self._queue_tts(current, index, segment):
                            return
                        index += 1
                if final:
                    self._queue_tts(current, index, None)
        except BaseException as exc:
            self._failure(current, exc)
            self.player.finish_production(identifier)

    def _run_tts(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.tts_jobs)
                if self.closed:
                    return
                current, index, text = self.tts_jobs.popleft()
                self.condition.notify_all()
                if current["cancel"].is_set():
                    continue
                if text is None:
                    self.player.finish_production(current["id"])
                    continue
                tts_id = f"{current['id']}-s{index}"
                current["tts_id"] = tts_id
            self._synthesize(current, tts_id, index, text)

    def _synthesize(self, current, tts_id, index, text):
        import numpy as np
        import soundfile as sf
        import soxr

        identifier = current["id"]
        try:
            self.record("tts_request", request_id=identifier, segment_id=tts_id, text=text)
            response = request(self.tts_socket, {"id": tts_id, "text": text,
                               "seed": current["seed"] + index}, timeout=90)
            self.record("tts_result", request_id=identifier, segment_id=tts_id, response=response)
            if current["cancel"].is_set() or response.get("cancelled"):
                self.record("late_audio_discarded", request_id=identifier, segment_id=tts_id)
                return
            audio, sr = sf.read(response["audio"], dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if sr != 16000:
                audio = soxr.resample(audio, sr, 16000)
            if not len(audio) or not np.isfinite(audio).all() or not np.max(np.abs(audio)) > 0:
                raise ValueError("TTS returned empty or invalid audio")
            self.player.enqueue(identifier, audio, text)
        except BaseException as exc:
            self._failure(current, exc)
            self.player.finish_production(identifier)
        finally:
            if current["cancel"].is_set():
                self.record("cancelled_tts_drained", request_id=identifier, segment_id=tts_id)

    def cancel(self, reason, transcribe=True):
        with self.condition:
            current = self.current
            if current is None:
                return
            current["cancel"].set()
            identifier = current["id"]
            if self.pending is not None and self.pending[0] is current:
                self.pending = None
                self.record("pending_generation_discarded", request_id=identifier)
            self.tts_jobs = deque(job for job in self.tts_jobs if job[0] is not current)
            self.condition.notify_all()
        self.record("cancel_requested", request_id=identifier, reason=reason)
        played = self.player.cancel(identifier)
        with self.condition:
            # The player's complete-segment ledger also covers a callback racing cancellation.
            current["spoken_text"] = played["text"]
            tail = played["tail"]
            repair = transcribe and len(tail) > 0
            if self.current is current:
                self._finalize(keep_empty=repair)
            if len(self.cancel_jobs) >= 128 or len(self.history_jobs) >= 128:
                raise RuntimeError("Cancellation cleanup exceeds the per-sample queue budget")
            self.cancel_jobs.append((identifier, current["tts_id"]))
            if repair:
                current["history_version"] += 1
                self.history_jobs.append((current, current["history_version"], tail))
                self.record("assistant_history_pending", request_id=identifier,
                            version=current["history_version"], tail_samples=len(tail),
                            committed_samples=played["committed_samples"])
            self.condition.notify_all()

    def _run_cleanup(self, history):
        while True:
            with self.condition:
                jobs = self.history_jobs if history else self.cancel_jobs
                self.condition.wait_for(lambda: self.closed or jobs)
                if not jobs:
                    if self.closed:
                        return
                    continue
                job = jobs.popleft()
            if history:
                current, version, tail = job
                try:
                    heard = self.recognize(tail, source="played_assistant_tail_history")
                    with self.condition:
                        if current["history_version"] == version:
                            entry = current["history_entry"]
                            entry["content"] = " ".join(p for p in (current["spoken_text"].strip(), heard.strip()) if p)
                            self.record("assistant_text_visible", request_id=current["id"], version=version,
                                        text=entry["content"], source="ASR_of_actual_played_tail")
                except BaseException as exc:
                    with self.condition:
                        self.errors.append(exc)
                    self.record("history_transcription_failure", request_id=current["id"], error=str(exc))
            else:
                identifier, tts_id = job
                for path, target in ((self.qwen_socket, identifier), (self.tts_socket, tts_id)):
                    if target is None:
                        continue
                    try:
                        response = request(path, {"operation": "cancel", "id": target}, timeout=3)
                        self.record("cancel_acknowledged", request_id=identifier, target_id=target, response=response)
                    except Exception as exc:
                        # Local cancellation remains authoritative when a backend is unavailable.
                        self.record("cancel_rpc_failure", request_id=identifier, target_id=target, error=str(exc))

    def check(self):
        if self.player.error:
            raise RuntimeError(f"Playback failure: {self.player.error}")
        with self.lock:
            if self.errors:
                raise RuntimeError(f"Generation/history failure: {self.errors[0]}") from self.errors[0]

    def close(self, minimum_seconds=0):
        cleanup_error = None
        try:
            self.cancel("sample_cleanup", transcribe=False)
        except BaseException as exc:
            cleanup_error = exc
        finally:
            with self.condition:
                self.closed = True
                self.pending = None
                self.tts_jobs.clear()
                self.condition.notify_all()
            try:
                self.player.close(minimum_seconds=minimum_seconds)
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
        deadline = time.monotonic() + 95
        for worker in self.workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in self.workers):
            raise RuntimeError("Reply workers did not exit; stop before the next sample")
        if cleanup_error:
            raise cleanup_error
        self.check()
