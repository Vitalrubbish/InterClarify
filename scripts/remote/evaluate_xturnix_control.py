"""Score frozen Listen observations, calibrate on dev, and evaluate held-out turns."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import importlib
import json
import math
from pathlib import Path
import random
import resource
import statistics
import subprocess
import time

REVISION = "d4b0403e5a6744b46fa7602b6d77bbac2768d5b5"


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def verify_model(model: Path, lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_text())
    if lock["revision"] != REVISION or lock["resolved_revision"] != REVISION:
        raise ValueError("model revision mismatch")
    for name, entry in lock["files"].items():
        path = model / name
        if path.stat().st_size != entry["bytes"] or file_sha(path) != entry["sha256"]:
            raise ValueError(f"model asset mismatch: {name}")
    return {"revision": REVISION, "verified_files": len(lock["files"]),
            "lock_sha256": file_sha(lock_path)}


def score(events: list[dict], pipe: object, output: Path) -> list[dict]:
    import torch

    prepare = importlib.import_module(pipe.__class__.__module__).prepare_messages
    rows = []
    with output.open("x") as stream:
        for index, event in enumerate(events, 1):
            row = {k: v for k, v in event.items() if k != "messages"}
            row.update({"p_start": None, "p_keep": None, "error": None,
                        "elapsed_ms": None, "dropped_history_messages": None,
                        "input_tokens": None, "status": "scored"})
            if event["preparation_error"] == "empty_current_prefix":
                row.update({"status": "abstain_empty_text", "elapsed_ms": 0.0})
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                continue
            started = time.perf_counter()
            try:
                if event["preparation_error"]:
                    raise ValueError(event["preparation_error"])
                prepared, state = prepare(event["messages"], state="listening")
                retained = pipe._truncate_history(prepared, state, 2048)
                row["dropped_history_messages"] = len(prepared) - len(retained)
                row["input_tokens"] = len(pipe.tokenizer.apply_chat_template(
                    retained, tokenize=True, add_generation_prompt=True, enable_thinking=False))
                torch.cuda.synchronize()
                started = time.perf_counter()
                result = pipe(event["messages"], state="listening")
                torch.cuda.synchronize()
                p = float(result["scores"]["<|start|>"])
                q = float(result["scores"]["<|keep|>"])
                if not math.isfinite(p + q) or abs(p + q - 1) > 1e-5:
                    raise ValueError("invalid pair-normalized scores")
                if not 0 <= p <= 1 or not 0 <= q <= 1:
                    raise ValueError("action score outside probability range")
                row.update({"p_start": p, "p_keep": q, "official_action": result["action"]})
            except Exception as exc:
                if isinstance(exc, torch.cuda.OutOfMemoryError):
                    raise
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["status"] = "failed"
            row["elapsed_ms"] = 1000 * (time.perf_counter() - started)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            if torch.cuda.max_memory_reserved() > 22 * 1024 ** 3:
                raise RuntimeError("22 GiB GPU reservation stop line exceeded")
            if index % 50 == 0:
                print(f"scored={index}/{len(events)} split={event['split']}", flush=True)
    return rows


def metrics(rows: list[dict], threshold: float) -> dict:
    turns = defaultdict(list)
    confusion = {"start_as_start": 0, "start_as_keep": 0,
                 "keep_as_start": 0, "keep_as_keep": 0}
    for row in rows:
        turns[row["turn_id"]].append(row)
        if row["p_start"] is not None:
            predicted = "start" if row["p_start"] >= threshold else "keep"
            confusion[row["target"] + "_as_" + predicted] += 1
    false_cutoffs = endpoint_hits = safe_hits = risk_turns = uncertain_turns = 0
    for samples in turns.values():
        hold = [r for r in samples if r["target"] == "keep"]
        end = [r for r in samples if r["target"] == "start"]
        if len(end) != 1:
            raise ValueError("planned turn must have exactly one terminal observation")
        early = any(r["p_start"] is not None and r["p_start"] >= threshold for r in hold)
        hit = end[0]["p_start"] is not None and end[0]["p_start"] >= threshold
        uncertain = any(r["p_start"] is None and r.get("status") != "abstain_empty_text" for r in hold)
        false_cutoffs += early
        endpoint_hits += hit
        safe_hits += hit and not early and not uncertain
        risk_turns += bool(hold)
        uncertain_turns += uncertain
    count = len(turns)
    return {"planned_turns": count, "planned_events": len(rows),
            "successful_events": sum(r["p_start"] is not None for r in rows),
            "failed_events": sum(r["p_start"] is None and r.get("status") != "abstain_empty_text" for r in rows),
            "abstained_empty_text_events": sum(r.get("status") == "abstain_empty_text" for r in rows),
            "risk_turns": risk_turns, "uncertain_hold_turns": uncertain_turns,
            "false_cutoffs": false_cutoffs, "false_cutoff_rate": false_cutoffs / count,
            "risk_conditional_false_cutoff_rate": false_cutoffs / risk_turns if risk_turns else None,
            "endpoint_hits": endpoint_hits, "endpoint_recall": endpoint_hits / count,
            "safe_endpoint_hits": safe_hits, "safe_endpoint_recall": safe_hits / count,
            "snapshot_confusion": confusion}


def choose_threshold(rows: list[dict], budget: float = 0.05) -> tuple[float, list[dict]]:
    if any(row["split"] != "dev" for row in rows):
        raise ValueError("threshold selection accepts development records only")
    if any(row["p_start"] is None and row.get("status") != "abstain_empty_text" for row in rows):
        raise ValueError("cannot calibrate with incomplete development predictions")
    values = {0.0, 0.5, math.nextafter(1.0, math.inf)}
    for row in rows:
        if row["p_start"] is None:
            continue
        values.add(row["p_start"])
        values.add(math.nextafter(row["p_start"], math.inf))
    curve, eligible = [], []
    for threshold in sorted(values):
        result = metrics(rows, threshold)
        point = {"threshold": threshold, **result}
        curve.append(point)
        if result["false_cutoff_rate"] <= budget:
            eligible.append(point)
    best = max(eligible, key=lambda r: (r["endpoint_recall"], -r["false_cutoff_rate"], r["threshold"]))
    return best["threshold"], curve


def paired_intervals(rows: list[dict], threshold: float) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row["conversation_id"]].append(row)
    names, rng = sorted(groups), random.Random(20261023)
    keys = ("endpoint_recall", "false_cutoff_rate", "safe_endpoint_recall")
    differences = {key: [] for key in keys}
    for _ in range(1000):
        sampled = []
        for copy, name in enumerate(rng.choices(names, k=len(names))):
            sampled.extend({**row, "turn_id": f"{copy}:{row['turn_id']}"} for row in groups[name])
        baseline, calibrated = metrics(sampled, 0.5), metrics(sampled, threshold)
        for key in keys:
            differences[key].append(calibrated[key] - baseline[key])
    return {key: {"delta_p025": sorted(values)[24], "delta_p975": sorted(values)[974]}
            for key, values in differences.items()}


def ranking(rows: list[dict]) -> dict:
    positive = [r["p_start"] for r in rows if r["target"] == "start" and r["p_start"] is not None]
    negative = [r["p_start"] for r in rows if r["target"] == "keep" and r["p_start"] is not None]
    auc = (sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
           / (len(positive) * len(negative))) if positive and negative else None
    return {"snapshot_roc_auc": auc, "positive_snapshots": len(positive),
            "negative_snapshots": len(negative), "unit": "correlated_pause_snapshots"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summary = json.loads((args.inputs / "prepare_summary.json").read_text())
    for split in ("dev", "test"):
        if file_sha(args.inputs / f"{split}.json.gz") != summary["inputs"][split]["sha256"]:
            raise ValueError("frozen inference input digest mismatch")
    model_evidence = verify_model(args.model, args.model_lock)
    import torch
    import transformers
    from transformers import pipeline

    if not torch.cuda.is_available():
        raise RuntimeError("a scheduler GPU is required")
    torch.set_num_threads(8)
    loaded = time.perf_counter()
    pipe = pipeline(model=str(args.model), trust_remote_code=True,
                    device=0, dtype="float32", local_files_only=True)
    if pipe._configured_max_length() != 2048:
        raise ValueError("unexpected model context contract")
    load_seconds = time.perf_counter() - loaded
    dev = json.loads(gzip.decompress((args.inputs / "dev.json.gz").read_bytes()))
    dev_rows = score(dev, pipe, args.output / "dev_scores.jsonl")
    threshold, curve = choose_threshold(dev_rows)
    write_json(args.output / "dev_curve.json", curve)
    frozen = {"threshold": threshold, "default_threshold": 0.5, "false_cutoff_budget": 0.05,
              "selected_from": "dev_only", "selection": "max_end_recall_then_min_cutoff_then_max_threshold",
              "dev_input_sha256": summary["inputs"]["dev"]["sha256"],
              "dev_default": metrics(dev_rows, 0.5), "dev_calibrated": metrics(dev_rows, threshold),
              "dev_ranking": ranking(dev_rows)}
    write_json(args.output / "threshold.json", frozen)
    print("threshold_frozen=" + str(threshold), flush=True)
    test = json.loads(gzip.decompress((args.inputs / "test.json.gz").read_bytes()))
    if {r["conversation_id"] for r in dev} & {r["conversation_id"] for r in test}:
        raise ValueError("development/test conversation leakage")
    test_rows = score(test, pipe, args.output / "test_scores.jsonl")
    baseline, calibrated = metrics(test_rows, 0.5), metrics(test_rows, threshold)
    timings = [r["elapsed_ms"] for r in dev_rows + test_rows if r["p_start"] is not None]
    intervals = paired_intervals(test_rows, threshold)
    report = {"schema": "xtx010-listen-calibration-result-v1", "scope": "offline_reference_text_listen_only",
              "model": model_evidence, "dtype": "float32", "transformers": transformers.__version__,
              "torch": torch.__version__, "gpu": torch.cuda.get_device_name(0),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "input_summary_sha256": file_sha(args.inputs / "prepare_summary.json"),
              "threshold_sha256": file_sha(args.output / "threshold.json"),
              "threshold": threshold, "test_default": baseline, "test_calibrated": calibrated,
              "test_ranking": ranking(test_rows),
              "paired_conversation_delta_ci95": intervals,
              "test_empirical_budget_met": calibrated["false_cutoff_rate"] <= 0.05 and calibrated["failed_events"] == 0,
              "resources": {"model_load_seconds": load_seconds,
                            "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                            "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            "inference_p50_ms": statistics.median(timings),
                            "inference_p95_ms": sorted(timings)[math.ceil(len(timings) * 0.95) - 1]},
              "dropped_history_events": sum(r["dropped_history_messages"] > 0
                                            for r in dev_rows + test_rows if r["dropped_history_messages"] is not None)}
    write_json(args.output / "summary.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
