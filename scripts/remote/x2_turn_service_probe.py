"""Stream one WAV file to the patched vLLM realtime endpoint and record frames.

The deployment work item only needs protocol evidence: raw ``turn.delta``
frames with their receive timestamps, the incremental transcription and a
summary that shows which native turn classes actually arrived.  Replay of the
full fixed subset, scoring and the complete-rate metric belong to the later
work items.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import websockets

TURN_ID_TO_NAME = {
    35: "idle",
    36: "noidle",
    37: "speaking",
    38: "turn_end",
    39: "backchannel",
    40: "uncertain",
}
COMPLETE_ID = 38
COMPLETE_NAME = "turn_end"
SAMPLE_RATE = 16000
CHUNK_MS = 80
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def read_pcm16(path: Path) -> tuple[np.ndarray, dict[str, object]]:
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError(f"{path}: expected mono 16-bit PCM WAV")
        if audio.getframerate() != SAMPLE_RATE:
            raise ValueError(f"{path}: expected {SAMPLE_RATE} Hz")
        frames = audio.getnframes()
        pcm = np.frombuffer(audio.readframes(frames), dtype=np.int16)
    return pcm, {
        "path": str(path),
        "frames": int(frames),
        "duration_seconds": round(frames / SAMPLE_RATE, 3),
    }


def chunk_pcm(pcm: np.ndarray, chunk_samples: int = CHUNK_SAMPLES) -> list[np.ndarray]:
    return [pcm[start : start + chunk_samples] for start in range(0, len(pcm), chunk_samples)]


def summarize(
    events: list[dict[str, object]], t_start: float, t_end: float
) -> dict[str, object]:
    """Aggregate raw events.  ``t_start``/``t_end`` are monotonic seconds."""
    counts: dict[str, int] = {}
    turns: list[dict[str, object]] = []
    text_parts: list[str] = []
    for event in events:
        payload = event["event"]
        counts[payload["type"]] = counts.get(payload["type"], 0) + 1
        if payload["type"] == "transcription.delta":
            text_parts.append(payload.get("delta", ""))
        elif payload["type"] == "turn.delta":
            class_id = int(payload["turn_id"])
            name = TURN_ID_TO_NAME.get(class_id)
            if name is None:
                raise ValueError(f"unknown turn id {class_id}")
            if payload.get("turn_class") != name:
                raise ValueError(
                    f"turn id {class_id} reported as {payload.get('turn_class')}, "
                    f"expected {name}"
                )
            turns.append(
                {
                    "frame_index": payload.get("frame_index"),
                    "turn_id": class_id,
                    "turn_class": name,
                    "probs": payload.get("probs"),
                    "recv_seconds": round(float(event["monotonic"]) - t_start, 6),
                    "after_end": float(event["monotonic"]) >= t_end,
                    "recv_utc": event["utc"],
                }
            )
    complete = [turn for turn in turns if turn["turn_id"] == COMPLETE_ID]
    after_end = [turn for turn in complete if turn["after_end"]]
    first_after_end_ms = (
        round((after_end[0]["recv_seconds"] - (t_end - t_start)) * 1000, 1)
        if after_end
        else None
    )
    class_counts: dict[str, int] = {}
    for turn in turns:
        class_counts[turn["turn_class"]] = class_counts.get(turn["turn_class"], 0) + 1
    return {
        "event_counts": counts,
        "transcript": "".join(text_parts),
        "turn_frames": turns,
        "turn_class_counts": class_counts,
        "complete": {
            "name": COMPLETE_NAME,
            "seen": bool(complete),
            "count": len(complete),
            "before_end_count": len(complete) - len(after_end),
            "after_end_count": len(after_end),
            "first_after_end_ms": first_after_end_ms,
        },
    }


async def _receive(
    websocket, events: list[dict[str, object]], stop: asyncio.Event
) -> None:
    try:
        async for message in websocket:
            monotonic = time.monotonic()
            payload = json.loads(message)
            events.append({"monotonic": monotonic, "utc": utc_now(), "event": payload})
            if stop.is_set():
                break
    except asyncio.CancelledError:
        raise


async def stream(
    url: str,
    model: str,
    pcm: np.ndarray,
    drain_seconds: float,
    chunk_ms: int = CHUNK_MS,
) -> dict[str, object]:
    chunk_samples = SAMPLE_RATE * chunk_ms // 1000
    chunks = chunk_pcm(pcm, chunk_samples)
    events: list[dict[str, object]] = []
    stop = asyncio.Event()
    lateness: list[float] = []
    async with websockets.connect(url, max_size=None, ping_interval=None) as websocket:
        created = json.loads(await websocket.recv())
        events.append({"monotonic": time.monotonic(), "utc": utc_now(), "event": created})
        receiver = asyncio.create_task(_receive(websocket, events, stop))
        await websocket.send(json.dumps({"type": "session.update", "model": model}))
        t_start = time.monotonic()
        for index, chunk in enumerate(chunks):
            deadline = t_start + index * chunk_ms / 1000.0
            delay = deadline - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            lateness.append(round(max(0.0, time.monotonic() - deadline) * 1000, 2))
            await websocket.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk.tobytes()).decode("ascii"),
                    }
                )
            )
            await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
        t_end = time.monotonic()
        await asyncio.sleep(drain_seconds)
        stop.set()
        receiver.cancel()
        try:
            await receiver
        except asyncio.CancelledError:
            pass
    summary = summarize(events, t_start, t_end)
    summary["send"] = {
        "chunks": len(chunks),
        "chunk_ms": chunk_ms,
        "drain_seconds": drain_seconds,
        "audio_seconds": round(len(pcm) / SAMPLE_RATE, 3),
        "max_lateness_ms": max(lateness) if lateness else 0.0,
        "mean_lateness_ms": round(float(np.mean(lateness)), 2) if lateness else 0.0,
        "t_start_monotonic": t_start,
        "t_end_monotonic": t_end,
    }
    return {"summary": summary, "events": events}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8011/v1/realtime")
    parser.add_argument("--model", default="x-square-robot/X2-Turn-4B-0812")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--drain-seconds", type=float, default=5.0)
    parser.add_argument("--chunk-ms", type=int, default=CHUNK_MS)
    args = parser.parse_args(argv)

    pcm, audio_info = read_pcm16(args.audio)
    result = asyncio.run(
        stream(args.url, args.model, pcm, args.drain_seconds, args.chunk_ms)
    )
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "summary.json", result["summary"])
    with (args.output / "events.jsonl").open("w", encoding="utf-8") as stream_file:
        for event in result["events"]:
            stream_file.write(json.dumps(event, ensure_ascii=False) + "\n")
    write_json(
        args.output / "probe.json",
        {
            "started_at": utc_now(),
            "url": args.url,
            "model": args.model,
            "audio": audio_info,
            "drain_seconds": args.drain_seconds,
            "chunk_ms": args.chunk_ms,
        },
    )
    summary = result["summary"]
    print(
        json.dumps(
            {
                "transcript": summary["transcript"],
                "turn_frames": len(summary["turn_frames"]),
                "turn_class_counts": summary["turn_class_counts"],
                "complete": summary["complete"],
                "max_lateness_ms": summary["send"]["max_lateness_ms"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not summary["transcript"].strip():
        raise SystemExit("empty transcript: the ASR head produced no text")
    if not summary["turn_frames"]:
        raise SystemExit("no turn.delta frames: the state head is not reporting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
