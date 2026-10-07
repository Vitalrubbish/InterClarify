#!/usr/bin/env python3
"""P1.1 offline sample of the official DuplexCascade control model.

Loads the fixed DuplexCascade weights (unmodified) and drives a scripted
micro-turn sequence through the official control-token generation loop, without
the real-time ASR/TTS services.  Saves the input script, raw per-turn output,
GPU peak memory and latency/RTF into a P0-style run directory.

Weight paths and the fixed input come from the command line (the cluster job
fills them from the P1.1 asset manifest).  This script adds no InterClarify
Layer 2 logic.

Usage
-----
    PYTHONPATH=src python scripts/run_p1_offline_sample.py \
        --profile cluster \
        --snapshot /path/to/.../sbintuitions--DuplexCascade/<rev> \
        --base-model-path /path/to/.../Qwen--Qwen2-7B-Instruct/<rev> \
        --output-root <artifact>/p1_offline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interclarify.config import resolve_paths  # noqa: E402
from interclarify.duplex.official_control import DEFAULT_SCRIPT, OfficialControlAdapter  # noqa: E402
from interclarify.run import RunContext  # noqa: E402


def _latest_child(path: Path) -> Optional[Path]:
    if not path.is_dir():
        return None
    children = sorted(p for p in path.iterdir() if p.is_dir())
    return children[-1] if children else None


def _resolve_snapshot(model_root: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidate = _latest_child(model_root / "modelscope" / "sbintuitions--DuplexCascade")
    if candidate is None:
        raise SystemExit(f"DuplexCascade snapshot not found under {model_root}/modelscope")
    return candidate


def _resolve_base_model(model_root: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidate = _latest_child(model_root / "modelscope" / "Qwen--Qwen2-7B-Instruct")
    if candidate is None:
        raise SystemExit(f"base model snapshot not found under {model_root}/modelscope")
    return candidate


def _load_script(path: Optional[Path]) -> List[Optional[str]]:
    if path is None:
        return list(DEFAULT_SCRIPT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("--script must be a JSON list of strings or nulls")
    return [None if item is None else str(item) for item in payload]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="cluster")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--snapshot", help="DuplexCascade snapshot dir")
    parser.add_argument("--base-model-path", help="base model snapshot dir")
    parser.add_argument("--source-root", help="official DuplexCascade checkout (model.py)")
    parser.add_argument("--script", type=Path, help="JSON list of micro-turn texts (null = silence)")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--micro-turn-seconds", type=float, default=0.6)
    args = parser.parse_args(argv)

    ctx = RunContext.create(
        output_root=args.output_root,
        profile=args.profile,
        config_dir=args.config_dir,
        run_id=args.run_id,
        tags=["p1", "offline-sample"],
    )
    try:
        paths = resolve_paths(ctx.config)
        repo_root = paths["repo_root"]
        model_root = paths["model_root"]
        source_root = (
            Path(args.source_root).expanduser().resolve()
            if args.source_root
            else repo_root / "3rd-party" / "DuplexCascade"
        )
        snapshot = _resolve_snapshot(model_root, args.snapshot)
        base_model = _resolve_base_model(model_root, args.base_model_path)
        script = _load_script(args.script)

        ctx.record(
            "offline_sample_start",
            snapshot=str(snapshot),
            base_model=str(base_model),
            source_root=str(source_root),
            script=script,
            device=args.device,
            dtype=args.dtype,
        )

        adapter = OfficialControlAdapter(
            snapshot_dir=snapshot,
            base_model_path=base_model,
            source_root=source_root,
            device=args.device,
            dtype=args.dtype,
            max_new_tokens=args.max_new_tokens,
            micro_turn_seconds=args.micro_turn_seconds,
        )

        results = adapter.run_script(script)
        for result in results:
            ctx.record(
                "micro_turn_generation",
                turn=result.index,
                user_text=result.user_text,
                prompt_tokens=result.prompt_tokens,
                generated_token_ids=result.generated_token_ids,
                assistant_special=result.assistant_special,
                assistant_text=result.assistant_text,
                latency_s=round(result.latency_s, 6),
            )

        peak = adapter.cuda_peak_memory_mb()
        peak_alloc_mb = peak["allocated"]
        peak_reserved_mb = peak["reserved"]

        total_latency = sum(result.latency_s for result in results)
        audio_time = args.micro_turn_seconds * len(results)
        metrics = {
            "snapshot": str(snapshot),
            "base_model": str(base_model),
            "device": args.device,
            "dtype": args.dtype,
            "num_turns": len(results),
            "micro_turn_seconds": args.micro_turn_seconds,
            "max_new_tokens": args.max_new_tokens,
            "total_latency_s": round(total_latency, 6),
            "mean_latency_s": round(total_latency / len(results), 6) if results else None,
            "rtf_vs_micro_turn": round(total_latency / audio_time, 6) if audio_time else None,
            "cuda_peak_allocated_mb": peak_alloc_mb,
            "cuda_peak_reserved_mb": peak_reserved_mb,
            "turns": [
                {
                    "turn": result.index,
                    "user_text": result.user_text,
                    "assistant_special": result.assistant_special,
                    "assistant_text": result.assistant_text,
                    "latency_s": round(result.latency_s, 6),
                    "num_generated_tokens": len(result.generated_token_ids),
                }
                for result in results
            ],
        }
        ctx.finalize(metrics)
    finally:
        ctx.close()

    summary = {"run_id": ctx.run_id, "run_dir": str(ctx.run_dir), "status": "PASS"}
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
