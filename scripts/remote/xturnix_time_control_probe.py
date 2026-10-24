"""Record bounded real-time ASR and frozen PT events for Listen comparisons."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
import urllib.request
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from compare_xturnix_latency import file_sha
from evaluate_xturnix_control import verify_model


def request(url: str, method: str = "GET", body: dict | None = None) -> dict:
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, payload, {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


class EventLog:
    """Serialize timestamps and sequence IDs from observer and inference threads."""

    def __init__(self, path: Path):
        self.started = time.monotonic()
        self.stream = path.open("x")
        self.lock = threading.RLock()
        self.sequence = 0
        self.emit("clock_origin", started_monotonic=self.started)

    def emit(self, kind: str, **values) -> None:
        with self.lock:
            self.sequence += 1
            record = {"at": time.monotonic() - self.started,
                      "sequence": self.sequence, "kind": kind, **values}
            self.stream.write(json.dumps(record, allow_nan=False) + "\n")
            self.stream.flush()


class LatestScorer(threading.Thread):
    """Keep one running inference and replace only the newest pending prefix."""

    def __init__(self, pipe, history: list[dict], log: EventLog):
        super().__init__(daemon=True)
        self.pipe, self.history, self.log = pipe, history, log
        self.condition = threading.Condition()
        self.pending = None
        self.stopping = False
        self.error = None
        self.calls = self.replaced = 0

    def submit(self, version: int, text: str) -> None:
        with self.condition:
            if self.pending is not None:
                self.replaced += 1
            self.pending = version, text
            self.condition.notify_all()

    def run(self) -> None:
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.stopping)
                if self.stopping:
                    return
                version, text = self.pending
                self.pending = None
            started = time.monotonic()
            self.calls += 1
            try:
                messages = self.history + [{"role": "user", "content": text}]
                input_sha = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
                value = self.pipe(messages, state="listening")
                score = float(value["scores"]["<|start|>"])
                if not 0 <= score <= 1:
                    raise ValueError("invalid action score")
                self.log.emit("score", text_version=version, p_start=score, input_sha256=input_sha,
                              elapsed_ms=1000 * (time.monotonic() - started))
                if getattr(getattr(self.pipe, "device", None), "type", None) == "cuda":
                    import torch

                    cleanup_started = time.monotonic()
                    allocated = torch.cuda.memory_allocated()
                    reserved = torch.cuda.memory_reserved()
                    torch.cuda.empty_cache()
                    self.log.emit("cache_cleanup", text_version=version,
                                  allocated_before_bytes=allocated, reserved_before_bytes=reserved,
                                  reserved_after_bytes=torch.cuda.memory_reserved(),
                                  elapsed_ms=1000 * (time.monotonic() - cleanup_started))
            except Exception as exc:
                self.error = repr(exc)
                self.log.emit("inference_error", text_version=version, error=self.error)
                return

    def close(self) -> None:
        with self.condition:
            self.stopping = True
            self.pending = None
            self.condition.notify_all()
        self.join(30)
        if self.is_alive():
            raise RuntimeError("inference worker failed to stop")


class AsrObserver(threading.Thread):
    """Record progress on every poll, versioning only effective text changes."""

    def __init__(self, base: str, identity: str, config: dict, normalize, scorer, log):
        super().__init__(daemon=True)
        self.base, self.identity, self.config = base, identity, config
        self.normalize, self.scorer, self.log = normalize, scorer, log
        self.stop_event = threading.Event()
        self.text, self.version = "", 0
        self.changed_at = None
        self.received = self.consumed = 0
        self.receive_at = self.consume_at = None
        self.error = None

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                snapshot = request(f"{self.base}/v1/session/{self.identity}/result")
                at = time.monotonic() - self.log.started
                received, consumed = snapshot["received_samples"], snapshot["consumed_samples"]
                if received > self.received:
                    self.receive_at = at
                if consumed > self.consumed:
                    self.consume_at = at
                self.received, self.consumed = received, consumed
                text = self.normalize(snapshot["text"])
                changed = text != self.text
                if changed:
                    self.text, self.version, self.changed_at = text, self.version + 1, at
                healthy = (self.receive_at is not None and self.consume_at is not None
                           and 1000 * (at - self.receive_at) <= self.config["receive_stale_ms"]
                           and 1000 * (at - self.consume_at) <= self.config["consume_stale_ms"]
                           and 1000 * (received - consumed) / 16000 <= self.config["backlog_limit_ms"]
                           and not snapshot["ended"])
                self.log.emit("snapshot", text_version=self.version, nonempty=bool(text),
                              changed_at=self.changed_at, healthy=healthy,
                              text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                              received_samples=received, consumed_samples=consumed)
                if changed and text:
                    self.scorer.submit(self.version, text)
            except Exception as exc:
                self.error = repr(exc)
                self.log.emit("observer_error", error=self.error)
                return
            self.stop_event.wait(self.config["poll_ms"] / 1000)

    def close(self) -> None:
        self.stop_event.set()
        self.join(31)
        if self.is_alive():
            raise RuntimeError("ASR observer failed to stop")
        self.log.emit("snapshot", text_version=self.version, nonempty=bool(self.text),
                      changed_at=self.changed_at, healthy=False,
                      received_samples=self.received, consumed_samples=self.consumed)


def replay(case: dict, manifest_dir: Path, pipe, normalize, base: str,
           config: dict, output: Path) -> dict:
    audio_path = manifest_dir / case["audio_path"]
    if file_sha(audio_path) != case["audio_sha256"]:
        raise ValueError("audio digest mismatch")
    with wave.open(str(audio_path)) as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError("expected normalized PCM16 mono 16kHz")
        pcm = stream.readframes(stream.getnframes())
    identity = request(base + "/v1/session", "POST", {})["session_id"]
    log = EventLog(output / "events" / f"{case['turn_id']}.jsonl")
    scorer = LatestScorer(pipe, case["history"], log)
    observer = AsrObserver(base, identity, config, normalize, scorer, log)
    status, error, cleanup_error = "completed", None, None
    maximum_send_lateness = 0.0
    scorer.start()
    observer.start()
    try:
        packet_bytes = int(32000 * config["packet_ms"] / 1000)
        transmitted = pcm + b"\0" * int(32000 * config["tail_seconds"])
        for start in range(0, len(transmitted), packet_bytes):
            end = min(start + packet_bytes, len(transmitted))
            deadline = log.started + end / 32000
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            maximum_send_lateness = max(maximum_send_lateness,
                                        1000 * (time.monotonic() - deadline))
            if observer.error or scorer.error:
                raise RuntimeError(observer.error or scorer.error)
            packet = transmitted[start:end]
            request(base + "/v1/recognize", "POST",
                    {"session_id": identity, "audio": base64.b64encode(packet).decode(),
                     "is_final": False, "end_stream": False})
            log.emit("audio", samples=end // 2, tail=start >= len(pcm),
                     send_lateness_ms=max(0, 1000 * (time.monotonic() - deadline)))
            if log.stream.tell() > config["max_output_bytes"] // 45:
                raise RuntimeError("per-case trace budget exceeded")
    except Exception as exc:
        status, error = "failed", repr(exc)
    finally:
        try:
            observer.close()
            scorer.close()
        except Exception as exc:
            cleanup_error = repr(exc)
        try:
            drained = request(base + "/v1/recognize", "POST",
                              {"session_id": identity, "audio": "", "end_stream": True})
            drained_text = normalize(drained["text"])
            log.emit("eof_drain", nonempty=bool(drained_text), ended=drained["ended"],
                     text_sha256=hashlib.sha256(drained_text.encode()).hexdigest())
            request(base + f"/v1/session/{identity}", "DELETE")
        except Exception as exc:
            cleanup_error = repr(exc)
        if observer.error or scorer.error or cleanup_error:
            status = "failed"
            error = error or observer.error or scorer.error or cleanup_error
        if maximum_send_lateness > config["packet_ms"]:
            status, error = "failed", error or "input schedule exceeded one packet of lateness"
        log.stream.close()
    result = {"turn_id": case["turn_id"], "status": status, "error": error,
              "cleanup_error": cleanup_error, "model_calls": scorer.calls,
              "replaced_pending": scorer.replaced, "asr_text_versions": observer.version,
              "maximum_send_lateness_ms": maximum_send_lateness}
    (output / "status" / f"{case['turn_id']}.json").write_text(json.dumps(result, indent=2) + "\n")
    if cleanup_error:
        raise RuntimeError("stream cleanup failed; refusing next session")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--asr-url", default="http://127.0.0.1:18815")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest, config = json.loads(args.manifest.read_text()), json.loads(args.config.read_text())
    if not manifest["audio_downloaded"] or manifest["config_sha256"] != file_sha(args.config):
        raise ValueError("audio or frozen configuration missing")
    verified = verify_model(args.model, args.model_lock)
    import torch
    import transformers
    from transformers import pipeline

    if not torch.cuda.is_available():
        raise RuntimeError("real probe requires a scheduler GPU")
    torch.set_num_threads(4)
    pipe = pipeline(model=str(args.model), trust_remote_code=True,
                    dtype="float32", device=0, local_files_only=True)
    if pipe._configured_max_length() != 2048:
        raise ValueError("unexpected context limit")
    normalize = importlib.import_module(pipe.__class__.__module__).strip_trailing_punctuation
    pipe([{"role": "user", "content": "Hello"}], state="listening")
    torch.cuda.synchronize()
    health = request(args.asr_url + "/health")
    if (health.get("backend") != "nemotron_en" or health.get("chunk_ms") != 160
            or health.get("dtype") != "torch.float32" or health.get("offline") is not False):
        raise ValueError("unexpected ASR service")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "events").mkdir()
    (args.output / "status").mkdir()
    execution = {"schema": "xtx014-short-latency-execution-v1", "model": verified,
                 "config_sha256": file_sha(args.config), "manifest_sha256": file_sha(args.manifest),
                 "source_commit": subprocess.check_output([
                     "git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"], text=True).strip(),
                 "torch": torch.__version__, "transformers": transformers.__version__,
                 "gpu": torch.cuda.get_device_name(0), "asr_health": health,
                 "pt_warmup_calls": 1,
                 "script_sha256": {name: file_sha(Path(__file__).resolve().parents[2] / name)
                                   for name in (
                                       "scripts/remote/xturnix_time_control_probe.py",
                                       "scripts/remote/nemotron_asr_service.py",
                                       "scripts/remote/run_xturnix_time_comparison.sh",
                                       "scripts/analysis/compare_xturnix_latency.py",
                                       "scripts/analysis/prepare_xturnix_short_latency.py")},
                 "scope": "real_clock_asr_and_pt_shadow_no_llm_tts"}
    (args.output / "execution.json").write_text(json.dumps(execution, indent=2) + "\n")
    started = time.monotonic()
    results = []
    for case in manifest["cases"]:
        results.append(replay(case, args.manifest.parent, pipe, normalize, args.asr_url,
                              config, args.output))
        print(json.dumps(results[-1]), flush=True)
        if time.monotonic() - started > config["max_job_seconds"] - 300:
            raise RuntimeError("bounded run deadline reached")
        if torch.cuda.max_memory_reserved() > 22 * 1024 ** 3:
            raise RuntimeError("GPU reservation budget exceeded")
    execution.update({"completed_turns": sum(r["status"] == "completed" for r in results),
                      "planned_turns": len(manifest["cases"]),
                      "elapsed_seconds": time.monotonic() - started,
                      "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved()})
    (args.output / "execution.json").write_text(json.dumps(execution, indent=2) + "\n")


if __name__ == "__main__":
    main()
