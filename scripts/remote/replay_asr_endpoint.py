"""Measure real official-weight text response starts from observed ASR trajectories."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path


CONFIGS = ["nemotron_en-160", "nemotron_en-560", "nemotron_multi-320", "nemotron_multi-560", "kyutai-500"]


def without_punctuation(text):
    """Remove sentence punctuation while preserving every other character."""
    return re.sub(r"[.,!?;:，。！？；：]", "", text)


def response_metrics(events, boundary, observation_end):
    """Count response identities, retaining continuations and later cancellations."""
    starts, updates, cancelled = {}, {}, set()
    for event in events:
        response_id = event.get("response_id", "")
        if event["kind"] == "text" and event.get("text", "").strip():
            starts.setdefault(response_id, event["at"])
            updates.setdefault(response_id, []).append(event["at"])
        elif event["kind"] == "cancel":
            cancelled.add(response_id)
    after = [(rid, at) for rid, at in starts.items() if boundary <= at <= observation_end]
    after.sort(key=lambda item: item[1])
    first = after[0] if after else None
    continuations = [rid for rid, at in starts.items() if at < boundary
                     and any(boundary <= t <= observation_end for t in updates[rid])]
    return {"first_new_reply_seconds": first[1] - boundary if first else None,
            "first_new_response_id": first[0] if first else None,
            "new_reply_within_2s": bool(first and first[1] - boundary <= 2),
            "new_reply_within_5s": bool(first and first[1] - boundary <= 5),
            "new_reply_within_12s": bool(first),
            "premature_response_ids": [rid for rid, at in starts.items() if at < boundary],
            "cross_boundary_continuation_ids": continuations,
            "cancelled_response_ids": sorted(cancelled),
            "first_new_reply_later_cancelled": bool(first and first[0] in cancelled)}


class OfficialBridge:
    """Adapt the existing official-weight stream to the existing runtime client contract."""

    def __init__(self, model, requests):
        self.model = model
        self.requests = requests

    async def stream(self, history):
        from duplex_model_service import GenerateRequest, HistoryTurn
        from xtalk.duplex_control.model_client import GenerationEnd

        request = GenerateRequest(history=[HistoryTurn(**turn) for turn in history], max_new_tokens=64)
        record = {"history": history, "started_monotonic": time.monotonic(), "generated_ids": []}
        self.requests.append(record)
        async for item in self.model.stream(request):
            if "error" in item:
                raise RuntimeError(item["error"])
            if "text" in item:
                yield item["text"]
            if "finish_reason" in item:
                record["generated_ids"] = list(item.get("token_ids", []))
                record["finished_monotonic"] = time.monotonic()
                yield GenerationEnd(item["finish_reason"], tuple(record["generated_ids"]))


class HTTPModelProxy:
    """Keep the model environment separate from the installed X-Talk client environment."""

    def __init__(self, url, info):
        self.url = url.rstrip("/")
        self.info = info

    async def stream(self, request):
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.url + "/generate", json=request.model_dump()) as response:
                response.raise_for_status()
                async for line in response.content:
                    yield json.loads(line)


async def replay_one(model, row, trace, variant, output, observation_seconds=12.0):
    from xtalk.duplex_control.micro_turn import MicroTurnAssembler
    from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter
    from xtalk.serving.event_bus import EventBus, EventDispatchMode
    from xtalk.serving.events import (ASRResultPartial, DuplexMicroTurnReady, DuplexProtocolError,
        DuplexProtocolParsed, LLMAgentResponseUpdate, TurnTTSStopRequested)

    bus = EventBus(enable_history=True, max_history=10000)
    session_id = f'endpoint-{variant}-{row["sample_id"].split("/")[-1]}'
    requests = []
    assembler = MicroTurnAssembler(bus, session_id, {"duplex_auto_tick": False})
    adapter = DuplexRuntimeAdapter(bus, session_id, {"duplex_model_client": OfficialBridge(model, requests)})
    events = []
    started = time.monotonic()
    first_text = asyncio.Event()
    deadline = row["boundary_seconds"] + observation_seconds

    async def observe(event):
        payload = {"at": time.monotonic() - started, "response_id": getattr(event, "response_id", ""),
                   "request_id": getattr(event, "request_id", "")}
        if isinstance(event, LLMAgentResponseUpdate):
            payload.update(kind="text", text=event.text)
        elif isinstance(event, TurnTTSStopRequested):
            payload.update(kind="cancel", reason=event.reason)
        elif isinstance(event, DuplexMicroTurnReady):
            payload.update(kind="micro_turn", text=event.text, delta=event.delta_text)
        elif isinstance(event, DuplexProtocolError):
            payload.update(kind="error", code=event.code if hasattr(event, "code") else str(event))
        else:
            payload.update(kind="control", state_token=getattr(event, "state_token", ""))
        events.append(payload)

    for event_class in (LLMAgentResponseUpdate, TurnTTSStopRequested, DuplexMicroTurnReady,
                        DuplexProtocolParsed, DuplexProtocolError):
        bus.subscribe(event_class, observe, priority=-50)

    async def produce():
        for event in trace:
            await asyncio.sleep(max(0, started + event["arrival_seconds"] - time.monotonic()))
            text = without_punctuation(event["text"]) if variant == "without_punctuation" else event["text"]
            await bus.publish(ASRResultPartial(session_id=session_id, text=text),
                              mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
            if text.strip():
                first_text.set()

    async def clock():
        await first_text.wait()
        next_tick = time.monotonic() + 0.6
        while time.monotonic() - started < deadline:
            await asyncio.sleep(max(0.001, next_tick - time.monotonic()))
            next_tick = max(time.monotonic(), next_tick + 0.6)
            await assembler.flush()

    producer = asyncio.create_task(produce())
    ticker = asyncio.create_task(clock())
    error = None
    try:
        await asyncio.sleep(max(0, started + deadline - time.monotonic()))
    except Exception as exc:
        error = repr(exc)
    finally:
        for task in (producer, ticker):
            task.cancel()
        results = await asyncio.gather(producer, ticker, return_exceptions=True)
        exceptions = [repr(r) for r in results if isinstance(r, Exception)
                      and not isinstance(r, asyncio.CancelledError)]
        if exceptions:
            error = "; ".join(exceptions)
        # Save measured events before cleanup cancellation can add new observations.
        measured_events = [e for e in events if e["at"] <= deadline]
        history = list(adapter.history)
        await assembler.shutdown()
        await adapter.shutdown()
        await bus.shutdown()
    result = {"sample_id": row["sample_id"], "variant": variant,
              "boundary_seconds": row["boundary_seconds"], "boundary_interval": row["boundary_interval"],
              "observation_seconds": observation_seconds, "error": error,
              **response_metrics(measured_events, row["boundary_seconds"], deadline),
              "protocol_errors": sum(e["kind"] == "error" for e in measured_events)}
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps(result, indent=2))
    (output / "events.json").write_text(json.dumps(measured_events, ensure_ascii=False, indent=2))
    (output / "requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2))
    (output / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2))
    return result


async def run(args):
    import inspect
    from duplex_model_service import GenerateRequest, HistoryTurn
    from xtalk.duplex_control.micro_turn import MicroTurnAssembler
    from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter

    files = [Path(__file__).with_name("duplex_model_service.py")]
    files += [Path(inspect.getfile(cls)) for cls in (MicroTurnAssembler, DuplexRuntimeAdapter)]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    if args.model_url:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(args.model_url.rstrip("/") + "/health") as response:
                response.raise_for_status()
                info = await response.json()
        if Path(info["checkpoint"]).resolve() != args.checkpoint.resolve() or Path(info["base_model"]).resolve() != args.base_model.resolve():
            raise ValueError("Model service assets do not match the fixed official checkpoint")
        model = HTTPModelProxy(args.model_url, info)
    else:
        import torch
        from duplex_model_service import OfficialDuplexModel
        torch.set_num_threads(4)
        model = OfficialDuplexModel(args.checkpoint, args.base_model)
    async for _ in model.stream(GenerateRequest(history=[HistoryTurn(role="user", text="What is two plus two?")], max_new_tokens=8)):
        pass
    manifest = json.loads(args.manifest.read_text())
    samples = [r for r in manifest["samples"] if r["split"] == "test"]
    results = []
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {"model": model.info, "source_sha256": hashes, "interval_seconds": 0.6,
                "note": "Existing X-Talk runtime, real-time trace replay, HTTP model" if args.model_url else "Existing X-Talk runtime, in-process model",
                "tts": False}
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    for config in CONFIGS:
        for variant in ("original", "without_punctuation"):
            for index, row in enumerate(samples, 1):
                trace_path = args.asr_run / config / f"sample-{index:04d}.jsonl"
                trace = [json.loads(line) for line in trace_path.read_text().splitlines()]
                result = await replay_one(model, row, trace, variant,
                    args.output / config / variant / row["sample_id"].split("/")[-1])
                result["config"] = config
                results.append(result)
                (args.output / "results.json").write_text(json.dumps(results, indent=2))
                print(json.dumps(result), flush=True)
    after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    if after != hashes:
        raise RuntimeError("Runtime source changed during endpoint measurement")
    summary = {}
    for config in CONFIGS:
        summary[config] = {}
        for variant in ("original", "without_punctuation"):
            rows = [r for r in results if r["config"] == config and r["variant"] == variant]
            summary[config][variant] = {"samples": len(rows),
                "errors": sum(bool(r["error"]) or r["protocol_errors"] > 0 for r in rows),
                "reply_within_2s": sum(r["new_reply_within_2s"] for r in rows),
                "reply_within_5s": sum(r["new_reply_within_5s"] for r in rows),
                "reply_within_12s": sum(r["new_reply_within_12s"] for r in rows),
                "new_reply_later_cancelled": sum(r["first_new_reply_later_cancelled"] for r in rows),
                "cross_boundary_continuations": sum(bool(r["cross_boundary_continuation_ids"]) for r in rows),
                "latencies_seconds": [r["first_new_reply_seconds"] for r in rows if r["first_new_reply_seconds"] is not None]}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asr-run", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--model-url")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
