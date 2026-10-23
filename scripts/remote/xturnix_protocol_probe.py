"""Verify the frozen Nemotron/XTurnix protocol on the dev recording.

This probe is diagnostic evidence for XTX-002. It is not a formal replay and
does not compute start latency or WER; XTX-003 owns the timed replay client.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKET_MS = 80
TAIL_PACKETS = 63  # 5.04 s at 80 ms, frozen by the replay contract


class ProbeError(RuntimeError):
    """Fail a protocol check without pretending the probe succeeded."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    """Load and reject a config that cannot represent the frozen protocol."""

    config = json.loads(path.read_text())
    if config.get("schema") != "xtx-002-xturnix-fleurs-config-v1":
        raise ProbeError(f"unexpected config schema: {config.get('schema')}")
    asr = config["asr"]
    xturnix = config["xturnix"]
    triggers = config["triggers"]
    pause = config["pause"]
    replay = config["replay_contract"]
    if asr["transport"]["packet_ms"] != PACKET_MS:
        raise ProbeError("transport packet must be 80 ms")
    if asr["chunk_ms"] != 160 or asr["lookahead_tokens"] != 1:
        raise ProbeError("ASR must stay on the frozen 160 ms / lookahead=1 setting")
    if asr["dtype"] != "float32" or xturnix["dtype"] != "float32":
        raise ProbeError("both components must stay FP32 in the frozen config")
    if xturnix["state"] != "listening":
        raise ProbeError("the probe only measures the Listen contract")
    if tuple(xturnix["allowed_actions"]) != ("<|start|>", "<|keep|>"):
        raise ProbeError("Listen actions must be exactly start/keep")
    if xturnix["scheduler"]["max_in_flight"] != 1:
        raise ProbeError("the control scheduler must allow one in-flight request")
    if triggers["on_pause_event"] or pause["enabled"]:
        raise ProbeError("this round freezes pause injection as disabled")
    if replay["max_in_flight_control_requests"] != 1:
        raise ProbeError("the replay contract must allow one in-flight control request")
    return config


def expand_home(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> tuple[int, dict[str, Any]]:
    """Return status and decoded JSON; preserve HTTP errors as evidence."""

    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            decoded = json.loads(body or b"{}")
        except json.JSONDecodeError:
            decoded = {"detail": body.decode("utf-8", "replace")[:500]}
        return error.code, decoded


class AsrClient:
    """Keep one session and one request in flight while polling versions."""

    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        status, body = http_json("GET", f"{self.base_url}/health", timeout=self.timeout)
        if status != 200:
            raise ProbeError(f"health returned {status}: {body}")
        return body

    def create(self) -> str:
        status, body = http_json("POST", f"{self.base_url}/v1/session",
                                 {}, timeout=self.timeout)
        if status != 200:
            raise ProbeError(f"create returned {status}: {body}")
        return body["session_id"]

    def recognize(self, session: str, pcm: bytes, *, is_final: bool = False,
                  end_stream: bool = False) -> dict[str, Any]:
        status, body = http_json(
            "POST",
            f"{self.base_url}/v1/recognize",
            {
                "session_id": session,
                "audio": base64.b64encode(pcm).decode(),
                "is_final": is_final,
                "end_stream": end_stream,
            },
            timeout=self.timeout,
        )
        if status != 200:
            raise ProbeError(f"recognize returned {status}: {body}")
        return body

    def result(self, session: str) -> tuple[int, dict[str, Any]]:
        return http_json("GET", f"{self.base_url}/v1/session/{session}/result",
                         timeout=self.timeout)

    def close(self, session: str) -> tuple[int, dict[str, Any]]:
        return http_json("DELETE", f"{self.base_url}/v1/session/{session}",
                         timeout=self.timeout)


class ResultObserver(threading.Thread):
    """Poll the result endpoint at the frozen interval and keep every version."""

    def __init__(self, client: AsrClient, session: str, interval: float):
        super().__init__(daemon=True)
        self.client = client
        self.session = session
        self.interval = interval
        self.stop_event = threading.Event()
        self.events: list[dict[str, Any]] = []
        self.error: str | None = None
        self._last_version = -1

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                status, snapshot = self.client.result(self.session)
            except Exception as error:  # noqa: BLE001 - preserve the failure as evidence
                self.error = repr(error)
                return
            if status != 200:
                self.error = f"result returned {status}: {snapshot}"
                return
            if snapshot["prefix_version"] != self._last_version:
                self._last_version = snapshot["prefix_version"]
                self.events.append({**snapshot, "observed_monotonic": time.monotonic()})
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=5)
        if self.is_alive():
            raise ProbeError("result observer did not stop")


def load_pcm16(path: Path) -> bytes:
    """Convert the frozen WAV to PCM16 without modifying the source file."""

    import numpy as np
    import soundfile as sf

    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if rate != 16000 or audio.shape[1] != 1 or not np.isfinite(audio).all():
        raise ProbeError("dev audio must be finite mono 16 kHz")
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def run_asr(config: dict[str, Any], dev_audio: Path, output_dir: Path) -> dict[str, Any]:
    """Run one dev session with a real pause marker, tail silence and cleanup."""

    asr = config["asr"]
    client = AsrClient(asr["service"]["base_url"], asr["service"]["request_timeout_seconds"])
    health = client.health()
    expected_model = str(expand_home(asr["local_path"]))
    checks = {
        "health": health.get("status") == "ok",
        "model": str(Path(health.get("model", "")).resolve()) == expected_model,
        "chunk": health.get("chunk_ms") == asr["chunk_ms"],
        "dtype": str(health.get("dtype", "")).removeprefix("torch.") == asr["dtype"],
        "warmup": health.get("warmup_sessions") == 2,
    }
    if not all(checks.values()):
        raise ProbeError(f"ASR health does not match the frozen config: {health}")

    pcm = load_pcm16(dev_audio)
    packet = int(16000 * PACKET_MS / 1000) * 2
    packets = [pcm[index:index + packet] for index in range(0, len(pcm), packet)]
    session = client.create()
    observer = ResultObserver(client, session, asr["service"]["poll_interval_ms"] / 1000)
    observer.start()
    pause_index = len(packets) // 2
    pause_monotonic = None
    started = time.monotonic()
    try:
        for index, chunk in enumerate(packets):
            deadline = started + index * PACKET_MS / 1000
            time.sleep(max(0.0, deadline - time.monotonic()))
            if index == pause_index:
                pause_monotonic = time.monotonic()
                client.recognize(session, chunk, is_final=True)
            else:
                client.recognize(session, chunk)
        for index in range(TAIL_PACKETS):
            deadline = started + (len(packets) + index) * PACKET_MS / 1000
            time.sleep(max(0.0, deadline - time.monotonic()))
            client.recognize(session, b"\x00\x00" * int(16000 * PACKET_MS / 1000))
        final = client.recognize(session, b"", end_stream=True)
    finally:
        observer.stop()

    versions = observer.events
    status, current = client.result(session)
    if status == 200 and (not versions or versions[-1]["prefix_version"] != current["prefix_version"]):
        versions.append({**current, "observed_monotonic": time.monotonic()})
    if observer.error:
        raise ProbeError(f"result observer failed: {observer.error}")
    if not versions:
        raise ProbeError("no ASR version was observed")

    texts = [item["text"] for item in versions]
    prefix_monotonic = all(
        later.startswith(earlier) for earlier, later in zip(texts, texts[1:])
    )
    before_pause = [item for item in versions
                    if pause_monotonic is not None
                    and item["observed_monotonic"] <= pause_monotonic]
    pause_text = before_pause[-1]["text"] if before_pause else ""
    resume_text = final["text"]
    pause_resume = bool(resume_text) and len(resume_text) > len(pause_text)

    close_status, close_body = client.close(session)
    missing_status, _ = client.result(session)
    second = client.create()
    second_final = client.recognize(
        second, pcm[: int(16000 * 1.0) * 2], end_stream=True
    )
    second_close, _ = client.close(second)
    remaining_status, _ = client.result(second)
    health_after = client.health()

    checks.update(
        {
            "prefix_monotonic": prefix_monotonic,
            "native_text": bool(final["text"].strip()),
            "pause_resume": pause_resume,
            "close": close_status == 200 and close_body.get("ok") is True,
            "closed_session_404": missing_status == 404,
            "second_session": bool(second_final["session_id"]) and second_close == 200,
            "second_closed_404": remaining_status == 404,
            "healthy_after_cleanup": health_after.get("status") == "ok",
        }
    )
    evidence = {
        "health": health,
        "dev_audio": str(dev_audio),
        "audio_bytes": len(pcm),
        "audio_sha256": sha256_bytes(pcm),
        "packet_ms": PACKET_MS,
        "packet_count": len(packets),
        "send_seconds": time.monotonic() - started,
        "pause_sent_monotonic": pause_monotonic,
        "pause_prefix_text": pause_text,
        "session_id": session,
        "versions": versions,
        "final": final,
        "close": close_body,
        "closed_session_status": missing_status,
        "second_session": {"final": second_final, "close_status": second_close,
                           "status_after_close": remaining_status},
        "health_after_cleanup": health_after,
        "checks": checks,
    }
    (output_dir / "asr_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def run_xturnix(config: dict[str, Any], model_dir: Path, final_text: str,
                output_dir: Path) -> dict[str, Any]:
    """Load the frozen official pipeline and verify normalization and actions."""

    import torch
    from transformers import pipeline

    sys.path.insert(0, str(model_dir))
    import turn_pipeline  # noqa: PLC0415 - loaded from the frozen model directory

    xturnix = config["xturnix"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    load_started = time.monotonic()
    pipe = pipeline(
        model=str(model_dir),
        trust_remote_code=True,
        device=0 if device == "cuda" else -1,
        dtype=xturnix["dtype"],
        local_files_only=True,
    )
    load_seconds = time.monotonic() - load_started
    configured_max = int(pipe._configured_max_length())
    checks = {
        "cuda": device == "cuda",
        "max_seq_length": configured_max == xturnix["max_seq_length"],
        "system_prompt": bool(turn_pipeline.SYSTEM_PROMPT),
    }

    calls: list[dict[str, Any]] = []
    normalization: list[dict[str, Any]] = []

    def call(text: str, state: str) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        sent = time.monotonic()
        try:
            result = pipe([{"role": "user", "content": text}], state=state)
        except Exception as error:  # noqa: BLE001 - preserve the failure as evidence
            raise ProbeError(f"XTurnix call failed for {state}: {error!r}") from error
        received = time.monotonic()
        allowed = turn_pipeline.ALLOWED_ACTIONS[turn_pipeline.normalize_state(state)]
        scores = result["scores"]
        valid = (
            result["action"] in allowed
            and set(scores) == set(allowed)
            and abs(sum(scores.values()) - 1.0) < 1e-5
        )
        record = {
            "request_id": request_id,
            "state": state,
            "raw_input": text,
            "normalized_input": turn_pipeline.strip_trailing_punctuation(text),
            "action": result["action"],
            "scores": scores,
            "allowed_actions": list(allowed),
            "send_monotonic": sent,
            "receive_monotonic": received,
            "inference_seconds": received - sent,
            "valid": valid,
        }
        calls.append(record)
        return record

    words = final_text.split()
    checkpoints = sorted({max(1, len(words) // 3), max(1, 2 * len(words) // 3), len(words)})
    for count in checkpoints:
        prefix = " ".join(words[:count])
        normalization.append({
            "raw": prefix,
            "normalized": turn_pipeline.strip_trailing_punctuation(prefix),
        })
        call(prefix, "listening")
    call(final_text, "listening")

    for case in ("Hello, world.", "Wait...  ", "No punctuation", "Question?!", "你好。"):
        prepared, state = turn_pipeline.prepare_messages(
            [{"role": "user", "content": case}], state="listening"
        )
        expected = turn_pipeline.strip_trailing_punctuation(case)
        normalization.append({
            "raw": case,
            "normalized": prepared[-1]["content"],
            "expected": expected,
            "state": state,
            "matches": prepared[-1]["content"] == expected,
        })

    raw_with_punctuation = final_text.rstrip() + "  ?!"
    raw_call = call(raw_with_punctuation, "listening")
    normalized_call = call(turn_pipeline.strip_trailing_punctuation(raw_with_punctuation),
                           "listening")
    normalization_same = (
        raw_call["action"] == normalized_call["action"]
        and max(abs(raw_call["scores"][name] - normalized_call["scores"][name])
                for name in raw_call["scores"]) < 1e-6
    )
    normalization_preserves_internal = (
        turn_pipeline.strip_trailing_punctuation("Hello, world.") == "Hello, world"
    )

    speaking = call(final_text, "speaking")

    context_error = None
    try:
        pipe([{"role": "user", "content": " ".join(["word"] * 3000)}], state="listening")
    except ValueError as error:
        context_error = str(error)
    except Exception as error:  # noqa: BLE001 - only ValueError proves the contract
        context_error = f"unexpected {type(error).__name__}: {error}"

    checks.update(
        {
            "listen_actions": all(item["valid"] for item in calls
                                  if item["state"] == "listening"),
            "normalization_matches": all(item.get("matches", True) for item in normalization)
            and normalization_same and normalization_preserves_internal,
            "context_limit_fails_closed": context_error is not None
            and "cannot fit max_length" in context_error,
            "speaking_contract": speaking["valid"]
            and speaking["action"] in ("<|stop|>", "<|keep|>"),
        }
    )

    if device == "cuda":
        torch.cuda.synchronize()
    peak_rss_kib = 0
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                peak_rss_kib = int(line.split()[1])
    except OSError:
        pass
    resources = {
        "device": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "load_seconds": load_seconds,
        "peak_rss_kib": peak_rss_kib,
        "gpu_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(0)) if device == "cuda" else 0,
        "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(0)) if device == "cuda" else 0,
        "gpu_total_bytes": int(torch.cuda.get_device_properties(0).total_memory) if device == "cuda" else 0,
    }
    evidence = {
        "model_path": str(model_dir),
        "revision": xturnix["revision"],
        "pipeline_version": __import__("transformers").__version__,
        "load_seconds": load_seconds,
        "max_seq_length": configured_max,
        "calls": calls,
        "normalization": normalization,
        "context_error": context_error,
        "resources": resources,
        "checks": checks,
    }
    (output_dir / "xturnix_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def main() -> int:
    """Run the dev probe and return non-zero when any frozen check fails."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dev-audio", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--asr-url")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    if args.asr_url:
        config["asr"]["service"]["base_url"] = args.asr_url
    model_dir = args.model or expand_home(config["xturnix"]["local_path"])
    if not (model_dir / "turn_pipeline.py").is_file():
        raise ProbeError(f"XTurnix model directory is incomplete: {model_dir}")
    args.output.mkdir(parents=True, exist_ok=True)

    started = utc_now()
    asr = run_asr(config, args.dev_audio, args.output)
    xturnix = run_xturnix(config, model_dir, asr["final"]["text"], args.output)
    checks = {**asr["checks"], **xturnix["checks"]}
    result = {
        "schema": "xtx-002-protocol-probe-v1",
        "started_at": started,
        "finished_at": utc_now(),
        "config": {"path": str(args.config.resolve()), "sha256": sha256_file(args.config)},
        "asr": asr,
        "xturnix": xturnix,
        "checks": checks,
        "passed": all(checks.values()),
    }
    target = args.output / "probe.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": checks,
                      "asr_final": asr["final"]["text"],
                      "listen_actions": [item["action"] for item in xturnix["calls"]
                                         if item["state"] == "listening"]}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as error:
        print(f"probe error: {error}", file=sys.stderr)
        raise SystemExit(1)
