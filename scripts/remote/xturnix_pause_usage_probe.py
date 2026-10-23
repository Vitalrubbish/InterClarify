"""Replay the official pending-pause contract against the frozen PT model."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

from evaluate_xturnix_control import file_sha, verify_model, write_json

PAUSE = "<|pause|>"
MODES = ("none", "pending", "eager")
OFFICIAL_REVISION = "5f0d9959edf1026588246efbed827b078cbb114c"


@dataclass
class PauseState:
    text: str = ""
    offsets: set[int] = field(default_factory=set)
    pending: int | None = None
    gate: bool = False
    latched: bool = False

    def update_text(self, text: str) -> None:
        if text == self.text:
            return
        if not text.startswith(self.text):
            raise ValueError("probe expects monotonic reference text")
        self.gate = False
        if self.pending is not None and len(text) > self.pending:
            self.offsets.add(self.pending)
            self.pending = None
        self.text = text

    def pause(self) -> None:
        self.gate = True
        if self.text:
            self.pending = len(self.text)

    def render(self, mode: str) -> str:
        if mode not in MODES:
            raise ValueError("unknown pause mode")
        offsets = set() if mode == "none" else set(self.offsets)
        if mode == "eager" and self.pending is not None:
            offsets.add(self.pending)
        value = self.text
        for offset in sorted(offsets, reverse=True):
            value = value[:offset] + PAUSE + value[offset:]
        return value

    def map_start(self, raw_start: bool) -> bool:
        if raw_start and self.gate and not self.latched:
            self.latched = True
            return True
        return False


def select_cases(input_file: Path) -> list[dict]:
    rows = json.loads(gzip.decompress(input_file.read_bytes()))
    if any(row["split"] != "dev" for row in rows):
        raise ValueError("pause mechanism probe accepts dev only")
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["turn_id"]].append(row)
    selected = sorted((name for name, values in grouped.items() if len(values) >= 2),
                      key=lambda name: hashlib.sha256(name.encode()).hexdigest())[:20]
    if len(selected) != 20:
        raise ValueError("expected 20 multi-pause development turns")
    cases = []
    for name in selected:
        observations = sorted(grouped[name], key=lambda row: row["observed_until"])
        events = []
        for row in observations:
            value = row["messages"][-1]["content"]
            for kind in ("text", "pause"):
                events.append({"kind": kind, "text": value,
                               "source_time": row["observed_until"], "target": row["target"]})
        cases.append({"case_id": name, "source": "reference_dev_diagnostic",
                      "history": observations[0]["messages"][:-1], "events": events})
    sanity = [
        ("en_question", ["What time should we leave tomorrow?"]),
        ("zh_question", ["那空气净化器应该一直开着，还是睡觉前开两小时就够了"]),
        ("resume_request", ["Could you help me", "Could you help me move this table?"]),
    ]
    for name, texts in sanity:
        events = []
        for index, text in enumerate(texts):
            for kind in ("text", "pause", "pause"):
                events.append({"kind": kind, "text": text, "source_time": None,
                               "target": "start" if index == len(texts) - 1 else "keep"})
        cases.append({"case_id": name, "source": "scripted_sanity", "history": [], "events": events})
    return cases


def run_probe(cases: list[dict], pipe: object, output: Path) -> dict:
    import torch

    cache, results = {}, []
    model_calls = errors = 0
    with (output / "events.jsonl").open("x") as stream:
        for case in cases:
            for mode in MODES:
                state, first_start, terminal = PauseState(), None, None
                pause_candidates = 0
                for index, event in enumerate(case["events"]):
                    if event["kind"] == "text":
                        state.update_text(event["text"])
                    else:
                        state.pause()
                    content = state.render(mode)
                    messages = case["history"] + [{"role": "user", "content": content}]
                    key = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
                    cached, error = key in cache, None
                    elapsed = 0.0
                    if not state.text:
                        score = None
                    elif cached:
                        score, error = cache[key]
                    else:
                        model_calls += 1
                        started = time.perf_counter()
                        try:
                            result = pipe(messages, state="listening")
                            torch.cuda.synchronize()
                            score = float(result["scores"]["<|start|>"])
                        except Exception as exc:
                            if isinstance(exc, torch.cuda.OutOfMemoryError):
                                raise
                            score, error = None, f"{type(exc).__name__}: {exc}"
                            errors += 1
                        elapsed = 1000 * (time.perf_counter() - started)
                        cache[key] = (score, error)
                    raw_start = score is not None and score >= 0.5
                    candidate = raw_start and state.gate
                    emitted = state.map_start(raw_start)
                    if emitted:
                        first_start = event["target"]
                    if event["kind"] == "pause":
                        pause_candidates += candidate
                        terminal = {"p_start": score, "candidate_start": candidate}
                    record = {"case_id": case["case_id"], "source": case["source"], "mode": mode,
                              "event_index": index, **event, "input_sha256": key,
                              "model_text": content, "pause_tokens": content.count(PAUSE),
                              "pending_offset": state.pending, "committed_offsets": sorted(state.offsets),
                              "gate": state.gate, "latched": state.latched, "p_start": score,
                              "candidate_start": candidate, "emitted_start": emitted,
                              "cached": cached, "elapsed_ms": elapsed, "error": error}
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                    if torch.cuda.max_memory_reserved() > 22 * 1024 ** 3:
                        raise RuntimeError("GPU reservation exceeds 22 GiB")
                results.append({"case_id": case["case_id"], "source": case["source"], "mode": mode,
                                "first_start_target": first_start, "pause_candidates": pause_candidates,
                                "terminal": terminal})
            print("completed_case=" + case["case_id"], flush=True)
    aggregates = {}
    for mode in MODES:
        selected = [r for r in results if r["mode"] == mode and r["source"] == "reference_dev_diagnostic"]
        aggregates[mode] = {"planned_turns": len(selected),
                            "terminal_candidate_start": sum(r["terminal"]["candidate_start"] for r in selected),
                            "early_first_start": sum(r["first_start_target"] == "keep" for r in selected),
                            "terminal_first_start": sum(r["first_start_target"] == "start" for r in selected),
                            "no_emitted_start": sum(r["first_start_target"] is None for r in selected)}
    return {"natural_dev": aggregates, "case_results": results,
            "actual_model_calls": model_calls, "unique_inference_errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    prepared = json.loads((args.inputs / "prepare_summary.json").read_text())
    dev_file = args.inputs / "dev.json.gz"
    if file_sha(dev_file) != prepared["inputs"]["dev"]["sha256"]:
        raise ValueError("development input digest mismatch")
    verified = verify_model(args.model, args.model_lock)
    cases = select_cases(dev_file)
    write_json(args.output / "case_manifest.json", [
        {"case_id": c["case_id"], "source": c["source"], "events": len(c["events"])} for c in cases])
    import torch
    import transformers
    from transformers import pipeline

    if not torch.cuda.is_available():
        raise RuntimeError("real model probe must run on a scheduler GPU")
    pipe = pipeline(model=str(args.model), trust_remote_code=True,
                    dtype="float32", device=0, local_files_only=True)
    if pipe._configured_max_length() != 2048:
        raise ValueError("unexpected context contract")
    pause_ids = pipe.tokenizer.encode(PAUSE, add_special_tokens=False)
    if pause_ids != [151674]:
        raise ValueError("pause token mapping changed")
    started = time.perf_counter()
    result = run_probe(cases, pipe, args.output)
    result.update({"schema": "xtx014-pause-usage-probe-v1", "official_revision": OFFICIAL_REVISION,
                   "model": verified, "pause_token_ids": pause_ids, "dtype": "float32",
                   "source_commit": subprocess.check_output([
                       "git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"], text=True).strip(),
                   "transformers": transformers.__version__, "torch": torch.__version__,
                   "gpu": torch.cuda.get_device_name(0), "elapsed_seconds": time.perf_counter() - started,
                   "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                   "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                   "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   "dev_input_sha256": file_sha(dev_file),
                   "scope": "reference_pause_contract_not_live_asr_or_full_xtalk"})
    write_json(args.output / "summary.json", result)
    if result["unique_inference_errors"]:
        raise RuntimeError("probe retained inference errors")
    print(json.dumps(result["natural_dev"]), flush=True)


if __name__ == "__main__":
    main()
