#!/usr/bin/env python3
"""P1.2 real-time duplex link: scripted scenarios against the official runtime.

This entry point keeps the official three-service architecture (separate Kyutai
STT/TTS services plus the unmodified ``server.py`` control model), optionally
launching the control model as a local subprocess from the verified snapshot,
and drives a continuous set of scripted scenarios through the headless duplex
client.  It produces the P1.2 acceptance evidence in a P0-style run directory:

- the system keeps receiving user audio while it is speaking
  (``frames_sent_while_speaking`` / ``user_barge_in`` events);
- silence, backchannel, regular answers, barge-in stop and resumed listening
  (per-scenario expectation checks);
- crash / queue-buildup / device-preemption proxies (send pacing underruns,
  playback backlog peaks, session timeouts).

Usage
-----
    PYTHONPATH=src python scripts/run_p1_2_live_link.py \
        --profile cluster \
        --output-root <artifact>/p1_2_live

    # connect to an already-running LLM service instead of launching one:
    PYTHONPATH=src python scripts/run_p1_2_live_link.py --profile replay \
        --llm connect --llm-url ws://127.0.0.1:31606/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interclarify.config import resolve_paths  # noqa: E402
from interclarify.duplex.official_server import (  # noqa: E402
    DEFAULT_TTS_VOICE,
    OfficialDuplexServer,
    verify_weight_sha256,
)
from interclarify.realtime.client import DuplexSessionClient, SessionResult  # noqa: E402
from interclarify.realtime.clock import make_clock  # noqa: E402
from interclarify.realtime.playback import SoundDevicePlaybackSink, VirtualPlaybackSink  # noqa: E402
from interclarify.realtime.scenarios import Scenario, load_scenarios, scenario_audio_digests  # noqa: E402
from interclarify.run import RunContext  # noqa: E402


def _latest_child(path: Path) -> Optional[Path]:
    if not path.is_dir():
        return None
    children = sorted(p for p in path.iterdir() if p.is_dir())
    return children[-1] if children else None


def _resolve_asset(model_root: Path, family: str, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidate = _latest_child(model_root / "modelscope" / family)
    if candidate is None:
        raise SystemExit(f"{family} snapshot not found under {model_root}/modelscope")
    return candidate


def _probe_ws(url: str, timeout_s: float = 3.0) -> Dict[str, Any]:
    """TCP reachability probe for a ws:// endpoint (no protocol handshake)."""
    import socket

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return {"url": url, "reachable": True}
    except OSError as exc:
        return {"url": url, "reachable": False, "error": str(exc)}


def _make_playback(kind: str, cfg: Dict[str, Any], clock, emit, sample_rate: int):
    audio = cfg.get("audio", {})
    if kind == "auto":
        kind = "sounddevice" if audio.get("output_device") else "virtual"
    if kind == "sounddevice":
        return SoundDevicePlaybackSink(sample_rate, emit, device=audio.get("output_device"))
    if kind == "virtual":
        return VirtualPlaybackSink(sample_rate, clock, emit)
    raise SystemExit(f"unknown playback sink kind {kind!r}")


def evaluate_expectations(scenario: Scenario, result: SessionResult, sample_rate: int = 24000) -> Dict[str, str]:
    """Check the recorded evidence against the scenario's declarative expectations."""
    checks: Dict[str, str] = {}
    expect = scenario.expect

    if expect.get("expect_no_asr"):
        checks["no_asr"] = "pass" if not result.asr_texts else "fail"
    if expect.get("answer_expected"):
        answered = result.answer_phase_count > 0 and result.tts_played_samples > 0
        checks["answer"] = "pass" if answered else "fail"
    if "min_tts_played_seconds" in expect:
        played = result.tts_played_samples / float(sample_rate)
        checks["min_tts_played"] = "pass" if played >= float(expect["min_tts_played_seconds"]) else "fail"
    needle = expect.get("user_asr_contains")
    if needle:
        checks["user_asr"] = "pass" if str(needle).lower() in result.last_asr_text().lower() else "fail"
    needle = expect.get("assistant_contains")
    if needle:
        checks["assistant_text"] = "pass" if str(needle).lower() in result.assistant_text.lower() else "fail"
    if expect.get("barge_in_stop_expected"):
        stopped = result.barge_in_count >= 1 and result.tts_cancelled_samples > 0
        checks["barge_in_stop"] = "pass" if stopped else "fail"
    if "backchannel_expected" in expect:
        if expect["backchannel_expected"]:
            checks["backchannel"] = "pass" if result.backchannel_count > 0 else "fail"
        else:
            checks["backchannel"] = "info"  # observed count recorded, not required
    return checks


async def _run_all(client: DuplexSessionClient, playback, scenarios: List[Scenario], reset_mode: str,
                   settle_seconds: float, run_dir: Path) -> List[SessionResult]:
    """Run every scenario continuously and return per-scenario deltas."""
    results: List[SessionResult] = []

    async def _run_one(scenario: Scenario) -> SessionResult:
        played0 = playback.played_samples
        cancelled0 = playback.cancelled_samples
        playback.max_backlog_samples = 0
        if isinstance(playback, VirtualPlaybackSink):
            playback.set_played_path(run_dir / "artifacts" / f"played_{scenario.name}.f32le")
        result = await client.run_scenario(scenario)
        # Playback counters are session-lifetime values; report per-scenario deltas.
        result.tts_played_samples = max(0, playback.played_samples - played0)
        result.tts_cancelled_samples = max(0, playback.cancelled_samples - cancelled0)
        result.playback_max_backlog_samples = playback.max_backlog_samples
        return result

    if reset_mode == "reconnect":
        for scenario in scenarios:
            await client.connect()
            try:
                results.append(await _run_one(scenario))
            finally:
                await client.close()
        return results

    await client.connect()
    try:
        for index, scenario in enumerate(scenarios):
            if index > 0:
                await client.send_reset(settle_seconds)
            results.append(await _run_one(scenario))
    finally:
        await client.close()
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="cluster")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--scenarios", type=Path, help="scenario JSON (default from config)")
    parser.add_argument("--scenario", help="comma-separated scenario filter")
    parser.add_argument("--audio-root", type=Path, help="scenario audio root (default from config)")
    parser.add_argument("--snapshot", help="DuplexCascade snapshot dir")
    parser.add_argument("--base-model-path", help="base model snapshot dir")
    parser.add_argument("--source-root", help="official DuplexCascade checkout (default 3rd-party)")
    parser.add_argument("--device", default=None)
    parser.add_argument("--dtype", default=None)
    parser.add_argument("--max-new-tokens", type=int, default=None)
    parser.add_argument("--micro-turn-seconds", type=float, default=None, dest="overlap_window_s")
    parser.add_argument("--stt-ws", default=None)
    parser.add_argument("--tts-ws", default=None)
    parser.add_argument("--tts-voice", default=None)
    parser.add_argument("--llm", choices=("launch", "connect"), default=None)
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--llm-port", type=int, default=None)
    parser.add_argument("--reset-mode", choices=("reset", "reconnect"), default=None)
    parser.add_argument("--playback-sink", choices=("auto", "virtual", "sounddevice"), default=None)
    parser.add_argument("--no-verify-weight", action="store_true")
    args = parser.parse_args(argv)

    ctx = RunContext.create(
        output_root=args.output_root,
        profile=args.profile,
        config_dir=args.config_dir,
        run_id=args.run_id,
        tags=["p1", "live-link"],
    )
    server: Optional[OfficialDuplexServer] = None
    playback = None
    started = time.monotonic()
    try:
        cfg = ctx.config
        paths = resolve_paths(cfg)
        repo_root = paths["repo_root"]
        duplex_cfg = dict(cfg.get("duplexcascade", {}))
        p1_2 = dict(cfg.get("p1_2", {}))

        scenarios_file = Path(args.scenarios) if args.scenarios else repo_root / str(p1_2.get("scenarios_path", "configs/p1_2_scenarios.json"))
        audio_root = Path(args.audio_root) if args.audio_root else repo_root / str(p1_2.get("scenario_audio_root", "assets/p1_2_scenarios"))
        scenarios = load_scenarios(scenarios_file, audio_root)
        if args.scenario:
            wanted = {name.strip() for name in args.scenario.split(",") if name.strip()}
            unknown = wanted - {scenario.name for scenario in scenarios}
            if unknown:
                raise SystemExit(f"unknown scenario(s): {sorted(unknown)}")
            scenarios = [scenario for scenario in scenarios if scenario.name in wanted]
        digests = scenario_audio_digests(scenarios)

        sample_rate = int(cfg.get("audio", {}).get("sample_rate", 24000))
        chunk_ms = float(cfg.get("audio", {}).get("chunk_ms", 80))
        frame_samples = int(round(sample_rate * chunk_ms / 1000.0))
        clock_mode = str(cfg.get("clock", {}).get("mode", "real"))

        for key, arg in (("stt_ws", args.stt_ws), ("tts_ws", args.tts_ws), ("tts_voice", args.tts_voice),
                         ("max_new_tokens", args.max_new_tokens), ("overlap_window_s", args.overlap_window_s)):
            if arg is not None:
                duplex_cfg[key] = arg
        device = args.device or str(cfg.get("device", {}).get("backend", "cuda"))
        dtype = args.dtype or "bfloat16"
        llm_mode = args.llm or str(p1_2.get("llm", "launch"))
        reset_mode = args.reset_mode or str(p1_2.get("reset_mode", "reset"))
        sink_kind = args.playback_sink or str(p1_2.get("playback_sink", "auto"))

        ctx.record(
            "live_link_start",
            scenarios_file=str(scenarios_file),
            audio_root=str(audio_root),
            scenarios=[scenario.name for scenario in scenarios],
            scenario_audio_sha256=digests,
            sample_rate=sample_rate,
            frame_samples=frame_samples,
            clock_mode=clock_mode,
            llm_mode=llm_mode,
            reset_mode=reset_mode,
            playback_sink=sink_kind,
            duplexcascade={k: duplex_cfg.get(k) for k in ("stt_ws", "tts_ws", "llm_port", "tts_voice", "max_new_tokens", "repo_commit", "hf_revision")},
        )

        # -- service probes (ASR/TTS are prerequisites) ----------------------
        probes = {
            "stt": _probe_ws(str(duplex_cfg["stt_ws"])),
            "tts": _probe_ws(str(duplex_cfg["tts_ws"])),
        }
        for name, result in probes.items():
            ctx.record("service_probe", service=name, **result)
            if not result["reachable"]:
                raise SystemExit(
                    f"{name.upper()} service not reachable at {result['url']} ({result.get('error')}); "
                    "start the Kyutai moshi-server instances first (see docs/jobs/p1_2_live_link.md)"
                )

        # -- control model service --------------------------------------------
        llm_port = args.llm_port or int(duplex_cfg.get("llm_port", 31606))
        if llm_mode == "launch":
            snapshot = _resolve_asset(paths["model_root"], "sbintuitions--DuplexCascade", args.snapshot)
            base_model = _resolve_asset(paths["model_root"], "Qwen--Qwen2-7B-Instruct", args.base_model_path)
            source_root = (
                Path(args.source_root).expanduser().resolve()
                if args.source_root
                else repo_root / "3rd-party" / "DuplexCascade"
            )
            weight_name = str(duplex_cfg.get("weight_filename", "model_state.safetensors"))
            weight_digest = None
            expected_digest = duplex_cfg.get("weight_sha256")
            if expected_digest and not args.no_verify_weight:
                weight_digest = verify_weight_sha256(snapshot, weight_name, str(expected_digest))
                ctx.record("weight_verified", snapshot=str(snapshot), filename=weight_name, sha256=weight_digest)
            server = OfficialDuplexServer(
                snapshot_dir=snapshot,
                base_model_path=base_model,
                source_root=source_root,
                llm_port=llm_port,
                stt_ws=str(duplex_cfg["stt_ws"]),
                tts_ws=str(duplex_cfg["tts_ws"]),
                device=device,
                dtype=dtype,
                max_new_tokens=int(duplex_cfg.get("max_new_tokens", 64)),
                overlap_window_s=float(duplex_cfg.get("overlap_window_s", cfg.get("clock", {}).get("micro_turn_seconds", 0.6))),
                api_key=str(duplex_cfg.get("api_key", "public_token")),
                tts_voice=str(duplex_cfg.get("tts_voice") or DEFAULT_TTS_VOICE),
                stt_pre_silence_s=float(duplex_cfg.get("stt_pre_silence_s", 0.0)),
                log_path=ctx.run_dir / "artifacts" / "official_server.log",
                ready_timeout_s=float(p1_2.get("llm_ready_timeout_s", 900)),
            )
            ctx.record(
                "llm_server_launch",
                snapshot=str(snapshot),
                base_model=str(base_model),
                source_root=str(source_root),
                device=device,
                dtype=dtype,
                llm_port=llm_port,
                log_path=str(ctx.run_dir / "artifacts" / "official_server.log"),
            )
            server.start()
            ctx.record("llm_server_ready", pid=server.process.pid if server.process else None, url=server.url)
            llm_url = server.url
        else:
            llm_url = args.llm_url or p1_2.get("llm_url") or f"ws://127.0.0.1:{llm_port}/"
            probe = _probe_ws(llm_url)
            ctx.record("service_probe", service="llm", **probe)
            if not probe["reachable"]:
                raise SystemExit(f"LLM service not reachable at {llm_url}; start it or use --llm launch")

        # -- duplex client -------------------------------------------------------
        clock = make_clock(clock_mode)
        emit = lambda event_type, **payload: ctx.record(event_type, **payload)  # noqa: E731
        playback = _make_playback(sink_kind, cfg, clock, emit, sample_rate)
        ctx.record(
            "playback_owner_ready",
            sink=type(playback).__name__,
            sample_rate=sample_rate,
            clock_mode=clock_mode,
        )
        client = DuplexSessionClient(
            url=llm_url,
            playback=playback,
            emit=emit,
            sample_rate=sample_rate,
            frame_samples=frame_samples,
            connect_timeout_s=float(p1_2.get("connect_timeout_s", 10)),
            post_audio_timeout_s=float(p1_2.get("post_audio_timeout_s", 30)),
            idle_gap_s=float(p1_2.get("idle_gap_s", 2.0)),
            no_tts_grace_s=float(p1_2.get("no_tts_grace_s", 8.0)),
            send_pace_budget_ms=float(p1_2.get("send_pace_budget_ms", 120)),
            chunk_event_stride=int(p1_2.get("chunk_event_stride", 1)),
        )

        results = asyncio.run(
            _run_all(
                client,
                playback,
                scenarios,
                reset_mode,
                float(p1_2.get("reset_settle_seconds", 1.5)),
                ctx.run_dir,
            )
        )

        scenario_rows = []
        all_checks: Dict[str, str] = {}
        for scenario, result in zip(scenarios, results):
            checks = evaluate_expectations(scenario, result, sample_rate)
            for key, value in checks.items():
                all_checks[f"{scenario.name}/{key}"] = value
            ctx.record("scenario_checks", scenario=scenario.name, checks=checks)
            scenario_rows.append(
                {
                    "name": scenario.name,
                    "checks": checks,
                    "duration_s": result.duration_s,
                    "control_sequence": result.control_sequence,
                    "last_asr_text": result.last_asr_text(),
                    "assistant_text": result.assistant_text[:500],
                    "answer_phase_count": result.answer_phase_count,
                    "backchannel_count": result.backchannel_count,
                    "barge_in_count": result.barge_in_count,
                    "server_barge_in_count": result.server_barge_in_count,
                    "frames_sent": result.frames_sent,
                    "frames_sent_while_speaking": result.frames_sent_while_speaking,
                    "tts_received_samples": result.tts_received_samples,
                    "tts_played_samples": result.tts_played_samples,
                    "tts_cancelled_samples": result.tts_cancelled_samples,
                    "playback_max_backlog_samples": result.playback_max_backlog_samples,
                    "send_underruns": result.send_underruns,
                    "max_send_gap_ms": result.max_send_gap_ms,
                }
            )

        failed = sorted(name for name, value in all_checks.items() if value == "fail")
        metrics = {
            "profile": args.profile,
            "llm_mode": llm_mode,
            "llm_url": llm_url,
            "clock_mode": clock_mode,
            "playback_sink": type(playback).__name__,
            "num_scenarios": len(scenarios),
            "scenarios": scenario_rows,
            "checks": all_checks,
            "checks_failed": failed,
            "duplex": {
                "scenarios_with_frames_while_speaking": sum(
                    1 for row in scenario_rows if row["frames_sent_while_speaking"] > 0
                ),
                "total_frames_while_speaking": sum(row["frames_sent_while_speaking"] for row in scenario_rows),
                "barge_in_stop_successes": sum(
                    1
                    for scenario, result in zip(scenarios, results)
                    if scenario.expect.get("barge_in_stop_expected")
                    and evaluate_expectations(scenario, result, sample_rate).get("barge_in_stop") == "pass"
                ),
            },
            "wall_duration_s": round(time.monotonic() - started, 3),
            "service_probes": probes,
        }
        ctx.record("continuous_run_summary", num_scenarios=len(scenarios), wall_duration_s=metrics["wall_duration_s"], checks_failed=failed)
        ctx.finalize(metrics)
    finally:
        if server is not None:
            server.stop()
        if playback is not None:
            playback.close()
        ctx.close()

    summary = {
        "run_id": ctx.run_id,
        "run_dir": str(ctx.run_dir),
        "checks_failed": metrics["checks_failed"],
        "status": "PASS" if not metrics["checks_failed"] else "CHECK_FAIL",
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0 if not metrics["checks_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
