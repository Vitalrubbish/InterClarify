#!/usr/bin/env python3
"""P0 deterministic offline smoke run.

Exercises the P0 deliverables end to end without any model inference:

1. load a profile configuration (default ``replay``);
2. create a run directory with ``manifest.json``, ``resolved_config.yaml``,
   ``environment.txt`` and ``events.jsonl``;
3. ingest a fixed-segment audio buffer (a WAV file via ``--input`` or a
   deterministic synthetic signal) and log one ``audio_chunk_received`` event
   per chunk;
4. write ``metrics.json``.

Running twice with the same input and configuration yields structurally
identical events and identical metrics, which is the P0 acceptance check
"same offline input under the same configuration produces structurally
consistent logs".

Usage
-----
    PYTHONPATH=src python scripts/run_p0_smoke.py --profile replay
    PYTHONPATH=src python scripts/run_p0_smoke.py --input path/to.wav --profile replay
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interclarify.run import RunContext  # noqa: E402


def _synthesize(sample_rate: int, seconds: float, seed: int):
    import numpy as np

    rng = np.random.default_rng(seed)
    n = int(round(sample_rate * seconds))
    time_axis = np.arange(n, dtype=np.float64) / sample_rate
    tone = 0.1 * np.sin(2.0 * np.pi * 440.0 * time_axis)
    noise = 0.001 * rng.standard_normal(n)
    return (tone + noise).astype("float32")


def _read_wav(path: Path, target_sample_rate: int):
    import numpy as np
    try:
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"--input requires soundfile: {exc}") from exc

    data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sample_rate != target_sample_rate:
        # Linear resample; sufficient for the P0 structural smoke run.
        duration = mono.shape[0] / float(sample_rate)
        n = int(round(duration * target_sample_rate))
        src = np.linspace(0.0, duration, num=mono.shape[0], endpoint=False)
        dst = np.linspace(0.0, duration, num=n, endpoint=False)
        mono = np.interp(dst, src, mono).astype("float32")
        sample_rate = target_sample_rate
    return mono


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="replay")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--input", type=Path, help="optional WAV input; synthesized if omitted")
    parser.add_argument("--seed", type=int, help="override run seed")
    parser.add_argument("--run-id", type=str)
    args = parser.parse_args(argv)

    overrides: Dict[str, Any] = {}
    if args.seed is not None:
        overrides.setdefault("run", {})["seed"] = args.seed

    ctx = RunContext.create(
        output_root=args.output_root,
        profile=args.profile,
        config_dir=args.config_dir,
        overrides=overrides or None,
        run_id=args.run_id,
        tags=["p0", "smoke"],
    )
    cfg = ctx.config
    audio_cfg = cfg.get("audio", {})
    sample_rate = int(audio_cfg.get("sample_rate", 16000))
    chunk_ms = int(audio_cfg.get("chunk_ms", 80))
    chunk_samples = max(1, int(round(sample_rate * chunk_ms / 1000.0)))
    seed = int(cfg.get("run", {}).get("seed", 0))

    try:
        if args.input:
            samples = _read_wav(args.input, sample_rate)
            source = str(args.input)
        else:
            samples = _synthesize(sample_rate, float(audio_cfg.get("smoke_seconds", 1.0)), seed)
            source = "synthetic"

        ctx.record("audio_input_opened", source=source, sample_rate=sample_rate, samples=int(samples.shape[0]))
        total = int(samples.shape[0])
        emitted = 0
        offset = 0
        while offset < total:
            chunk = samples[offset : offset + chunk_samples]
            emitted += 1
            ctx.record(
                "audio_chunk_received",
                seq=emitted,
                sample_offset=offset,
                num_samples=int(chunk.shape[0]),
                chunk_ms=chunk_ms,
            )
            offset += chunk_samples
        ctx.record("audio_input_closed", chunks=emitted)

        import numpy as np

        metrics = {
            "input_source": source,
            "sample_rate": sample_rate,
            "chunk_samples": chunk_samples,
            "num_chunks": emitted,
            "total_samples": total,
            "total_bytes": total * 4,
            "duration_s": round(total / float(sample_rate), 6),
            "rms": float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) if total else 0.0,
        }
        ctx.finalize(metrics)
    finally:
        ctx.close()

    summary = {
        "run_id": ctx.run_id,
        "run_dir": str(ctx.run_dir),
        "status": "PASS",
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
