"""Compare frozen Listen policies using actual arrival and score events."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def partition(conversation: str, config: dict) -> str:
    value = hashlib.sha256((config["partition_seed"] + conversation).encode()).hexdigest()
    return "calibration" if int(value, 16) % 2 == 0 else "evaluation"


def candidates(config: dict, budget: int) -> list[dict]:
    """Enumerate a bounded grid without inspecting outcomes."""
    thresholds = config["thresholds"]
    result = [{"family": "text", "times_ms": [0], "thresholds": [t]} for t in thresholds]
    result += [{"family": "time", "times_ms": [w], "thresholds": [0.0]}
               for w in config["waits_ms"] if w <= budget]
    result.append({"family": "time", "times_ms": [math.inf], "thresholds": [0.0]})
    for values in itertools.combinations_with_replacement(thresholds, 3):
        result.append({"family": "joint", "times_ms": config["joint_times_ms"][str(budget)],
                       "thresholds": list(reversed(values))})
    return result


def first_start(events: list[dict], policy: dict, config: dict) -> float | None:
    """Consume only causal observations, rejecting stale model versions."""
    version = score_version = None
    score = None
    nonempty = healthy = False
    changed_at = snapshot_at = None
    for event in events:
        at = event["at"]
        if event["kind"] == "snapshot":
            version = event["text_version"]
            nonempty = event["nonempty"]
            healthy = event["healthy"]
            changed_at = event["changed_at"]
            snapshot_at = at
        elif event["kind"] == "score":
            if event["text_version"] == version:
                score, score_version = event["p_start"], version
        elif event["kind"] == "observer_error":
            healthy = False
            continue
        else:
            continue
        if not healthy or not nonempty or changed_at is None or snapshot_at is None:
            continue
        if (at - snapshot_at) * 1000 > config["poll_stale_ms"]:
            continue
        idle_ms = (at - changed_at) * 1000
        for wait, threshold in zip(policy["times_ms"], policy["thresholds"]):
            if idle_ms + 1e-6 < wait:
                continue
            if policy["family"] == "time":
                return at
            if score_version == version and score is not None and score >= threshold:
                return at
    return None


def metrics(cases: list[dict], actions: dict[str, float | None], budget: int,
            anchor_key: str = "word_end") -> dict:
    """Count first actions once per planned turn, retaining failed cases."""
    early = hits = late = missing = failures = 0
    latencies = []
    for case in cases:
        failed = case["status"] != "completed"
        failures += failed
        action = actions[case["turn_id"]]
        if action is None:
            missing += 1
            continue
        latency = action - case[anchor_key]
        if latency < -1e-6:
            early += 1
        elif failed:
            missing += 1
        elif latency <= budget / 1000 + 1e-6:
            hits += 1
            latencies.append(max(0.0, latency))
        else:
            late += 1
    count = len(cases)
    return {"planned_turns": count, "failed_turns": failures, "early_turns": early,
            "early_rate": early / count if count else None, "safe_deadline_hits": hits,
            "safe_deadline_recall": hits / count if count else None,
            "late_turns": late, "no_action_turns": missing,
            "successful_median_latency_ms": statistics.median(latencies) * 1000 if latencies else None}


def compare(cases: list[dict], traces: dict[str, list[dict]], config: dict) -> dict:
    """Select on calibration only, then evaluate the frozen candidates."""
    calibration = [c for c in cases if c["partition"] == "calibration"]
    evaluation = [c for c in cases if c["partition"] == "evaluation"]
    if not calibration or not evaluation:
        raise ValueError("both conversation partitions must be nonempty")
    if any(c["status"] != "completed" for c in calibration):
        return {"schema": "xtx014-short-latency-comparison-v1",
                "scope": "exploratory_previously_viewed_dev_not_independent_test",
                "status": "incomplete_calibration_no_policy_selected",
                "primary_budget_ms": config["primary_budget_ms"],
                "failed_calibration_turns": [c["turn_id"] for c in calibration
                                             if c["status"] != "completed"], "results": []}
    results = []
    for budget in config["budgets_ms"]:
        policies = candidates(config, budget)
        for family in ("text", "time", "joint"):
            winner = None
            for index, policy in enumerate(policies):
                if policy["family"] != family:
                    continue
                actions = {c["turn_id"]: first_start(traces[c["turn_id"]], policy, config)
                           for c in calibration}
                measured = metrics(calibration, actions, budget)
                if measured["early_rate"] > config["false_cutoff_budget"]:
                    continue
                latency = measured["successful_median_latency_ms"]
                key = (measured["safe_deadline_hits"], -measured["early_turns"],
                       -(latency if latency is not None else math.inf), -index)
                if winner is None or key > winner[0]:
                    winner = key, policy, measured
            if winner is None:
                raise ValueError("missing abstain candidate")
            _, policy, measured = winner
            actions = {c["turn_id"]: first_start(traces[c["turn_id"]], policy, config)
                       for c in evaluation}
            results.append({"budget_ms": budget, "family": family,
                            "policy": {**policy, "times_ms": [None if math.isinf(x) else x
                                                               for x in policy["times_ms"]]},
                            "calibration": measured,
                            "evaluation": metrics(evaluation, actions, budget),
                            "silence_anchor_sensitivity": metrics(evaluation, actions, budget, "silence_start"),
                            "evaluation_actions": actions})
    return {"schema": "xtx014-short-latency-comparison-v1",
            "scope": "exploratory_previously_viewed_dev_not_independent_test",
            "status": "completed" if all(c["status"] == "completed" for c in cases)
                      else "incomplete_evaluation_failures_retained",
            "primary_budget_ms": config["primary_budget_ms"], "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    manifest = json.loads(args.manifest.read_text())
    execution = json.loads((args.run / "execution.json").read_text())
    if execution["config_sha256"] != file_sha(args.config):
        raise ValueError("configuration differs from executed run")
    if execution["manifest_sha256"] != file_sha(args.manifest):
        raise ValueError("manifest differs from executed run")
    cases, traces = [], {}
    for case in manifest["cases"]:
        status_path = args.run / "status" / f"{case['turn_id']}.json"
        status = json.loads(status_path.read_text()) if status_path.exists() else {"status": "skipped"}
        cases.append({**case, "status": status["status"]})
        trace_path = args.run / "events" / f"{case['turn_id']}.jsonl"
        events = [json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
        if any(not math.isfinite(e["at"]) for e in events):
            raise ValueError("non-finite event time")
        traces[case["turn_id"]] = sorted(events, key=lambda e: (e["at"], e["sequence"]))
    result = compare(cases, traces, config)
    result["provenance"] = execution
    version_audit = {"score_results": 0, "stale_score_results": 0, "healthy_snapshots": 0,
                     "snapshots": 0, "inference_errors": 0, "observer_errors": 0}
    elapsed = []
    for events in traces.values():
        current = None
        for event in events:
            if event["kind"] == "snapshot":
                current = event["text_version"]
                version_audit["snapshots"] += 1
                version_audit["healthy_snapshots"] += bool(event["healthy"])
            elif event["kind"] == "score":
                version_audit["score_results"] += 1
                version_audit["stale_score_results"] += event["text_version"] != current
                elapsed.append(event["elapsed_ms"])
            elif event["kind"] == "inference_error":
                version_audit["inference_errors"] += 1
            elif event["kind"] == "observer_error":
                version_audit["observer_errors"] += 1
    result["event_audit"] = version_audit
    result["model_compute_median_ms"] = statistics.median(elapsed) if elapsed else None
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
