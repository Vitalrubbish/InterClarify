#!/usr/bin/env python3
"""Synthesize the P1.2 scenario speech audio through the pinned Kyutai TTS service.

The scenario file (``configs/p1_2_scenarios.json``) is tracked in Git and
references one wav per speech segment.  This script generates those wavs with
the same Kyutai TTS service used by the official runtime, so the scripted user
is acoustically consistent with the system voice.  Silence segments
(``audio: null``) need no file -- the runner generates zeros in memory.

Only segments carrying ``synth_text`` are synthesized; existing files are
overwritten on every run so audio always matches the tracked text.  Print a
JSON summary with per-file durations and SHA-256 digests; the live-link runner
re-hashes the files into its run manifest for provenance.

Usage
-----
    PYTHONPATH=src python scripts/prepare_p1_2_scenarios.py --profile cluster
    PYTHONPATH=src python scripts/prepare_p1_2_scenarios.py --profile cluster --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402


def _build_tts_ws_url(base_ws_url: str, voice: str, api_key_qs: Optional[str]) -> str:
    """Mirror of server.py ``_build_tts_ws_url`` (format/voice/auth query params)."""
    parsed = urlparse(base_ws_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("format", "PcmMessagePack")
    if voice:
        query["voice"] = voice
    if api_key_qs:
        query.setdefault("auth_id", api_key_qs)
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _connect(url: str, api_key: str):
    """websockets 12/13+ compatible connect with the Kyutai auth header."""
    import websockets

    signature = inspect.signature(websockets.connect)
    kwargs: Dict[str, Any] = {}
    if api_key:
        if "additional_headers" in signature.parameters:
            kwargs["additional_headers"] = {"kyutai-api-key": api_key}
        else:
            kwargs["extra_headers"] = {"kyutai-api-key": api_key}
    return await websockets.connect(url, max_size=8 << 20, open_timeout=15, **kwargs)


async def synthesize_text(
    tts_ws: str,
    text: str,
    voice: str,
    api_key: str = "public_token",
    eos_timeout_s: float = 5.0,
    sample_rate: int = 24000,
) -> np.ndarray:
    """Synthesize one utterance; returns 24 kHz mono float32 samples.

    Sends ``Text`` + ``Eos`` and collects ``Audio`` frames until the stream
    idles past ``eos_timeout_s`` (the Kyutai service streams audio roughly in
    real time and does not send an explicit end marker on this endpoint).
    """
    import msgpack
    import websockets

    url = _build_tts_ws_url(tts_ws, voice=voice, api_key_qs=(api_key or None))
    chunks: List[List[float]] = []
    async with await _connect(url, api_key) as ws:
        await ws.send(msgpack.packb({"type": "Text", "text": text}, use_bin_type=True))
        await ws.send(msgpack.packb({"type": "Eos"}, use_bin_type=True))
        last_audio = time.monotonic()
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=eos_timeout_s)
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break
            message = msgpack.unpackb(raw, raw=False)
            if not isinstance(message, dict):
                continue
            if message.get("type") == "Audio":
                pcm = [float(x) for x in message.get("pcm", [])]
                if pcm:
                    chunks.append(pcm)
                    last_audio = time.monotonic()
            elif str(message.get("type", "")).lower() in ("eos", "end", "endofstream"):
                break
            if time.monotonic() - last_audio > eos_timeout_s:
                break
    if not chunks:
        raise RuntimeError(f"TTS produced no audio for text: {text!r}")
    return np.concatenate([np.asarray(chunk, dtype=np.float32) for chunk in chunks])


def _iter_synth_segments(payload: Dict[str, Any]):
    """Yield (scenario, segment) pairs that carry synth_text."""
    for scenario in payload.get("scenarios", []):
        for segment in scenario.get("segments", []):
            if segment.get("synth_text"):
                yield scenario, segment


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="cluster")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--audio-root", type=Path)
    parser.add_argument("--tts-ws", default=None)
    parser.add_argument("--tts-voice", default=None)
    parser.add_argument("--api-key", default="public_token")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--eos-timeout-s", type=float, default=5.0)
    parser.add_argument("--lead-silence-s", type=float, default=0.10)
    parser.add_argument("--tail-silence-s", type=float, default=0.30)
    parser.add_argument("--dry-run", action="store_true", help="print the work plan without synthesizing")
    args = parser.parse_args(argv)

    from interclarify.config import load_config, resolve_paths

    cfg = load_config(profile=args.profile, config_dir=args.config_dir)
    paths = resolve_paths(cfg)
    repo_root = paths["repo_root"]
    p1_2 = cfg.get("p1_2", {})
    scenarios_file = (
        Path(args.scenarios)
        if args.scenarios
        else repo_root / str(p1_2.get("scenarios_path", "configs/p1_2_scenarios.json"))
    )
    audio_root = (
        Path(args.audio_root)
        if args.audio_root
        else repo_root / str(p1_2.get("scenario_audio_root", "assets/p1_2_scenarios"))
    )
    duplex_cfg = cfg.get("duplexcascade", {})
    tts_ws = args.tts_ws or str(duplex_cfg.get("tts_ws"))
    voice = args.tts_voice or str(duplex_cfg.get("tts_voice", ""))

    payload = json.loads(scenarios_file.read_text(encoding="utf-8"))
    plan = []
    for scenario, segment in _iter_synth_segments(payload):
        rel_audio = segment.get("audio")
        if not rel_audio:
            raise SystemExit(
                f"scenario {scenario.get('name')!r} segment {segment.get('label')!r} has synth_text but no audio path"
            )
        plan.append(
            {
                "scenario": scenario.get("name"),
                "label": segment.get("label"),
                "text": segment["synth_text"],
                "audio": str(audio_root / rel_audio),
            }
        )

    summary = {"tts_ws": tts_ws, "voice": voice, "dry_run": args.dry_run, "files": []}
    if args.dry_run:
        summary["files"] = plan
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        return 0

    async def _run_all() -> List[Dict[str, Any]]:
        rows = []
        for item in plan:
            pcm = await synthesize_text(
                tts_ws,
                item["text"],
                voice=voice,
                api_key=args.api_key,
                eos_timeout_s=args.eos_timeout_s,
                sample_rate=args.sample_rate,
            )
            if args.lead_silence_s > 0 or args.tail_silence_s > 0:
                pad_lead = np.zeros(int(args.lead_silence_s * args.sample_rate), dtype=np.float32)
                pad_tail = np.zeros(int(args.tail_silence_s * args.sample_rate), dtype=np.float32)
                pcm = np.concatenate([pad_lead, pcm, pad_tail])
            out_path = Path(item["audio"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out_path), pcm, args.sample_rate, subtype="FLOAT")
            import hashlib

            digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
            rows.append(
                {
                    **item,
                    "samples": int(pcm.size),
                    "seconds": round(pcm.size / float(args.sample_rate), 3),
                    "sha256": digest,
                }
            )
        return rows

    summary["files"] = asyncio.run(_run_all())
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
