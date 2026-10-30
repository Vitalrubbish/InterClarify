"""Probe XTurnix start decisions with and without synthetic pause tokens.

This is a diagnostic probe, not the frozen XTX-005/006 replay.  It loads the
frozen XTurnix checkpoint once and scores the same final text under three
conditions:

1. no pause token;
2. one ``<|pause|>`` appended after the text;
3. one random in-text ``<|pause|>`` plus one appended at the end.

The probe uses the 5 test ASR transcripts saved by the XTX-005 smoke and the
100 FLEURS reference texts as a larger text-only sensitivity check.  It never
loads Nemotron and never writes into a formal run directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAUSE = "<|pause|>"
CONFIGS = (
    "no_pause",
    "pause_at_end",
    "pause_mid_and_end",
    "pause_at_end_stripped",
    "pause_mid_and_end_stripped",
)
STRIPPED_CONFIGS = {"pause_at_end_stripped", "pause_mid_and_end_stripped"}
TEXT_SETS = ("asr_smoke_test", "asr_smoke_dev", "reference_test", "sanity")
SANITY_CASES = (
    {
        "case_set": "sanity",
        "case_id": "zh_question_model_card",
        "text": "那空气净化器应该一直开着，还是睡觉前开两小时就够了",
    },
    {
        "case_set": "sanity",
        "case_id": "en_question_what_time",
        "text": "What time should we leave tomorrow?",
    },
    {
        "case_set": "sanity",
        "case_id": "en_question_help_move",
        "text": "Could you help me move this table?",
    },
    {
        "case_set": "sanity",
        "case_id": "en_statement_weather",
        "text": "The weather is nice today.",
    },
    {
        "case_set": "sanity",
        "case_id": "zh_statement_weather",
        "text": "今天天气不错。",
    },
)


def strip_trailing_punctuation(text: str) -> str:
    """Mirror the frozen turn_pipeline trailing-punctuation rule."""
    normalized = text.rstrip()
    while normalized and unicodedata.category(normalized[-1]).startswith("P"):
        normalized = normalized[:-1].rstrip()
    return normalized


def choose_pause_offset(text: str, rng: random.Random) -> int | None:
    """Choose a deterministic inter-word offset in the middle 60% of the text."""
    spaces = [
        index
        for index, char in enumerate(text)
        if char == " " and 0 < index < len(text) - 1
    ]
    if not spaces:
        return None
    low, high = int(len(text) * 0.2), int(len(text) * 0.8)
    middle = [index for index in spaces if low <= index <= high]
    return rng.choice(middle or spaces)


def with_pause(text: str, config: str, offset: int | None = None) -> str:
    """Return the exact user content for one probe condition."""
    if config == "no_pause":
        return text
    if config == "pause_at_end":
        return text + PAUSE
    if config == "pause_mid_and_end":
        if offset is None:
            return text + PAUSE
        return text[:offset] + PAUSE + text[offset:] + PAUSE
    if config in STRIPPED_CONFIGS:
        base = strip_trailing_punctuation(text)
        if config == "pause_at_end_stripped":
            return base + PAUSE
        if offset is None:
            return base + PAUSE
        return base[:offset] + PAUSE + base[offset:] + PAUSE
    raise ValueError(f"unsupported config: {config}")


def read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object with a clear error."""
    if not path.is_file():
        raise SystemExit(f"missing input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_asr_texts(run_dir: Path, label: str) -> list[dict[str, str]]:
    """Read final ASR texts from a scored replay's samples.csv."""
    path = run_dir / "score" / "samples.csv"
    if not path.is_file():
        raise SystemExit(f"missing scored samples: {path}")
    cases: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            text = (row.get("final_text") or row.get("online_text") or "").strip()
            if not text:
                continue
            cases.append(
                {
                    "case_set": label,
                    "case_id": row["sample_id"],
                    "text": text,
                }
            )
    return cases


def read_reference_texts(root: Path) -> list[dict[str, str]]:
    """Read the frozen 100 test references as a text-only sensitivity set."""
    manifest = read_json(root / "dataset" / "fleurs_en_us" / "manifest.json")
    cases: list[dict[str, str]] = []
    for sample in manifest["samples"]:
        if sample.get("split") != "test":
            continue
        text = sample.get("reference", "").strip()
        if text:
            cases.append(
                {
                    "case_set": "reference_test",
                    "case_id": sample["sample_id"],
                    "text": text,
                }
            )
    if len(cases) != 100:
        raise SystemExit(f"expected 100 test references, found {len(cases)}")
    return cases


def load_pipeline(model_dir: Path, expected_max_length: int) -> Any:
    """Load the frozen XTurnix transformers pipeline once."""
    import transformers
    from transformers import pipeline

    pipe = pipeline(
        model=str(model_dir),
        trust_remote_code=True,
        device=0,
        dtype="float32",
        local_files_only=True,
    )
    configured = int(pipe._configured_max_length())
    if configured != expected_max_length:
        raise SystemExit(
            f"max_seq_length {configured} != frozen {expected_max_length}"
        )
    return pipe, transformers.__version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", default="xtx-pause-probe-20261023")
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        runner_files = {"probe.log", "gpu.csv", "exit_code.txt"}
        extra = {path.name for path in output.iterdir()} - runner_files
        if extra:
            raise SystemExit(f"probe output already exists: {output} ({sorted(extra)})")
    output.mkdir(parents=True, exist_ok=True)

    config = read_json(args.config)
    run_dir = root / "runs" / args.source_run
    cases = read_asr_texts(run_dir / "replay", "asr_smoke_test")
    cases += read_asr_texts(run_dir / "replay-dev", "asr_smoke_dev")
    cases += read_reference_texts(root)
    cases += [dict(case) for case in SANITY_CASES]
    if not cases:
        raise SystemExit("no text cases loaded")

    import torch

    pipe, transformers_version = load_pipeline(
        args.model, int(config["xturnix"]["max_seq_length"])
    )
    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    for case in cases:
        for config_name in CONFIGS:
            rng = random.Random(f"{args.seed}:{case['case_id']}:{config_name}")
            base = (
                strip_trailing_punctuation(case["text"])
                if config_name in STRIPPED_CONFIGS
                else case["text"]
            )
            offset = choose_pause_offset(base, rng)
            content = with_pause(case["text"], config_name, offset)
            sent = time.monotonic()
            result = pipe(
                [{"role": "user", "content": content}], state="listening"
            )
            elapsed_ms = (time.monotonic() - sent) * 1000
            scores = {key: float(value) for key, value in result["scores"].items()}
            rows.append(
                {
                    "case_set": case["case_set"],
                    "case_id": case["case_id"],
                    "config": config_name,
                    "action": result["action"],
                    "start_score": scores.get("<|start|>"),
                    "keep_score": scores.get("<|keep|>"),
                    "mid_offset": offset,
                    "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "content": content,
                    "elapsed_ms": round(elapsed_ms, 3),
                }
            )

    csv_path = output / "samples.csv"
    fieldnames = [
        "case_set",
        "case_id",
        "config",
        "action",
        "start_score",
        "keep_score",
        "mid_offset",
        "content_sha256",
        "content",
        "elapsed_ms",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary: dict[str, Any] = {}
    for case_set in TEXT_SETS:
        summary[case_set] = {}
        for config_name in CONFIGS:
            subset = [
                row
                for row in rows
                if row["case_set"] == case_set and row["config"] == config_name
            ]
            starts = sum(row["action"] == "<|start|>" for row in subset)
            summary[case_set][config_name] = {
                "samples": len(subset),
                "starts": starts,
                "start_rate": round(starts / len(subset), 9) if subset else None,
                "mean_start_score": (
                    round(
                        sum(row["start_score"] for row in subset) / len(subset), 9
                    )
                    if subset
                    else None
                ),
            }

    payload = {
        "schema": "xtx-pause-probe-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "diagnostic_only": True,
        "note": (
            "Synthetic pause tokens appended/injected after the recording. "
            "This is not the frozen XTX-005/006 protocol and must not be merged "
            "into formal metrics."
        ),
        "source_run": args.source_run,
        "source_run_dir": str(run_dir),
        "model": str(args.model),
        "config": {
            "path": str(args.config),
            "sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        },
        "seed": args.seed,
        "device": device,
        "torch": torch.__version__,
        "transformers": transformers_version,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "configs": list(CONFIGS),
        "cases": {
            case_set: sum(case["case_set"] == case_set for case in cases)
            for case_set in TEXT_SETS
        },
        "summary": summary,
        "rows": str(csv_path),
    }
    (output / "probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\ncase_set,config,samples,starts,start_rate")
    for case_set in TEXT_SETS:
        for config_name in CONFIGS:
            item = summary[case_set][config_name]
            print(
                f"{case_set},{config_name},{item['samples']},"
                f"{item['starts']},{item['start_rate']}"
            )


if __name__ == "__main__":
    main()
