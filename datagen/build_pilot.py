"""Build auditable semantic SFT views from a small simulated event corpus."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATES = {f"user_{name}" for name in ("idle", "nonidle", "incomplete", "complete", "backchannel")}
MODULES = ("soulx", "layer1", "layer2")
PROMPTS = {
    "soulx": "依据当前可见观察判断用户状态。未来澄清语义单列，不扩充原生五状态。分析是外部条件，不是话轮指令。",
    "layer1": "根据当前输入组织自身行为。普通回答须读到有效 complete；保留取消与播放事实。分析仅作条件，不朗读。",
    "layer2": "仅分析当前任务的事实、缺口、依赖、结论与更新依据；不输出话轮建议、候选问句或表达草稿。",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def materialize(source, branch):
    events = deepcopy(source.get("shared_events", []) + branch["events"])
    decisions = deepcopy(source.get("shared_decisions", []) + branch["decisions"])
    require(len({e["id"] for e in events}) == len(events), "Duplicate event ID")
    require(len({d["id"] for d in decisions}) == len(decisions), "Duplicate decision ID")
    events.sort(key=lambda e: (e["at_ms"], e["id"]))
    decisions.sort(key=lambda d: (d["read_ms"], d["id"]))
    return events, decisions


def visible_input(source, decision, index):
    """Select explicitly consumed observations, never the whole script."""
    seen = [index[key] for key in decision["seen"]]
    require(len(set(decision["seen"])) == len(seen), "Duplicate consumed event")
    require(all(e["at_ms"] <= decision["read_ms"] for e in seen), "Future event in model input")
    require(all(e["kind"] != "script" for e in seen), "Hidden script in model input")
    frontend = [e for e in seen if e["kind"] == "frontend"]
    require(frontend, "A visible frontend snapshot is required")
    current = max(frontend, key=lambda e: e["at_ms"])
    module = decision["module"]
    payload = deepcopy(current["payload"])
    if module != "soulx":
        payload.pop("audio", None)
    else:
        payload.pop("raw_state", None)
        payload.pop("effective_complete", None)
    analyses = []
    observations = []
    for event in seen:
        if event["kind"] == "analysis":
            analyses.append({"event_id": event["id"], "published_ms": event["at_ms"], **deepcopy(event["payload"])})
        elif event["kind"] not in ("frontend", "script"):
            observations.append({"event_id": event["id"], "kind": event["kind"], **deepcopy(event["payload"])})
    if module == "soulx" and analyses:
        require(decision.get("scope") == "future_cot_control", "Native controller cannot consume CoT")
    model_input = {
        "task_information": source["task_information"],
        "current_user": payload,
        "observations": observations,
        "external_analysis": analyses,
    }
    return model_input, current


def check_events(events, index):
    tasks = {}
    publications = defaultdict(list)
    outputs = {}
    for event in events:
        kind, payload = event["kind"], event["payload"]
        require(event["at_ms"] >= 0, "Negative event time")
        if kind == "frontend":
            require(payload["raw_state"] in STATES, "Invalid native state")
            require(payload["raw_ready_ms"] <= event["at_ms"], "Publication precedes raw result")
            require(payload["audio"]["observed_until_ms"] <= payload["raw_ready_ms"], "Audio from the future")
            require(not payload["effective_complete"] or payload["raw_state"] == "user_complete", "Invalid complete")
        elif kind == "task":
            task_id, state = payload["task_id"], payload["state"]
            require(state in {"active", "completed", "failed", "timeout"}, "Invalid task lifecycle")
            if state == "active":
                require(not any(v == "active" for v in tasks.values()), "Concurrent thinking tasks")
            else:
                require(tasks.get(task_id) == "active", "Closing a nonactive task")
            tasks[task_id] = state
        elif kind == "analysis":
            task_id = payload["task_id"]
            require(tasks.get(task_id) == "active", "Publication outside active thinking task")
            require(payload["read_ms"] <= payload["finished_ms"] <= event["at_ms"], "Invalid analysis timing")
            require(payload["basis_frontend"] in index, "Unknown analysis basis")
            basis = index[payload["basis_frontend"]]
            require(basis["kind"] == "frontend" and basis["at_ms"] <= payload["read_ms"], "Future analysis basis")
            require(payload["version"] == len(publications[task_id]) + 1, "Nonsequential analysis version")
            publications[task_id].append(event)
        elif kind == "output":
            require(payload["phase"] in {"generated", "submitted", "synthesized", "playing", "closed"}, "Invalid output phase")
            require(payload["heard_any"] == bool(event.get("audit", {}).get("played_text", "")), "Played history differs")
            require(payload["generated_text"].startswith(event.get("audit", {}).get("played_text", "")), "Playback is not a generated prefix")
            previous = outputs.get(payload["output_id"])
            if previous:
                require(payload["generated_text"].startswith(previous["payload"]["generated_text"]), "Generated history replaced")
                require(event["audit"]["played_text"].startswith(previous["audit"]["played_text"]), "Played history rolled back")
            outputs[payload["output_id"]] = event
        elif kind == "runtime" and payload["event"] == "cancel_confirmed":
            prior = [e for e in events if e["kind"] == "output" and e["at_ms"] <= event["at_ms"] and e["payload"]["output_id"] == payload["output_id"]]
            require(prior, "Cancellation without an output")
            last = max(prior, key=lambda e: e["at_ms"])
            require(payload["heard_any"] == last["payload"]["heard_any"], "Cancellation lost played history")
            require(not any(e["kind"] == "output" and e["at_ms"] > event["at_ms"] and e["payload"]["output_id"] == payload["output_id"] and e["payload"]["phase"] != "closed" for e in events), "Cancelled output reused")


def check_generation(events, decisions):
    """Match simulated generated text to a preceding expression target."""
    generated = {}
    for event in events:
        if event["kind"] != "output":
            continue
        payload = event["payload"]
        previous = generated.get(payload["output_id"], "")
        text = payload["generated_text"]
        if text != previous:
            if event.get("audit", {}).get("origin") != "fixed_error_prefix":
                suffix = text[len(previous):]
                require(any(d["module"] == "layer1" and d["finish_ms"] <= event["at_ms"] and d["target"].get("text") == suffix for d in decisions), "Generated text has no preceding expression target")
            else:
                require(not any(d["module"] == "layer1" and d["target"].get("text") == text for d in decisions), "Fixed error is a positive target")
            generated[payload["output_id"]] = text
    for event in events:
        if event["kind"] == "controller":
            payload = event["payload"]
            require(payload["protocol_scope"] == "future_cot_control", "Unmarked future control publication")
            require(any(d["module"] == "soulx" and d["finish_ms"] <= event["at_ms"] and d["target"] == payload["judgment"] for d in decisions), "Control publication has no preceding target")


def check_target(decision, model_input, current, index):
    module, target = decision["module"], decision["target"]
    require(decision["finish_ms"] >= decision["read_ms"], "Generation ends before input construction")
    if module == "soulx":
        require(set(target) <= {"user_state", "intervention"}, "Controller contains an expression target")
        require(target["user_state"] is None or target["user_state"] in STATES, "Invalid controller target")
        require(target["user_state"] is not None or decision.get("uncertain"), "Uncertain label must be explicit")
        require("intervention" not in target or decision.get("scope") == "future_cot_control", "Clarification folded into five states")
    elif module == "layer1":
        require(set(target) <= {"action", "purpose", "text", "response_key", "output_id", "task_id"}, "Invalid Layer 1 fields")
        action = target["action"]
        require(action in {"wait", "request_thinking", "speak", "continue_expression"}, "Invalid Layer 1 action")
        seen = [index[key] for key in decision["seen"]]
        if action == "speak" and target["purpose"] == "ordinary":
            require(current["payload"]["effective_complete"], "Ordinary answer without visible effective complete")
            answered = [e for e in seen if e["kind"] == "output" and e["payload"].get("response_key") == target["response_key"]]
            require(not answered, "Repeated ordinary answer")
        if action == "speak" and target["purpose"] == "clarification":
            require(decision.get("scope") == "future_clarification", "Missing independent clarification boundary")
            require(any(e["kind"] == "controller" and e["payload"]["basis_frontend"] == current["id"] and e["payload"]["judgment"].get("intervention") == "clarification_opportunity" for e in seen), "Clarification without consumed future control boundary")
        if action == "request_thinking":
            states = {}
            for event in sorted(seen, key=lambda e: e["at_ms"]):
                if event["kind"] == "task":
                    states[event["payload"]["task_id"]] = event["payload"]["state"]
            require("active" not in states.values(), "Repeated request for an active task")
        if action == "continue_expression":
            output_id = target["output_id"]
            require(any(e["kind"] == "output" and e["payload"]["output_id"] == output_id for e in seen), "Continuation without generated history")
            require(not any(e["kind"] == "runtime" and e["payload"]["event"] == "cancel_confirmed" and e["payload"]["output_id"] == output_id for e in seen), "Continuation of cancelled output")
        if action in {"wait", "request_thinking"}:
            require("text" not in target, "Internal action contains spoken text")
    else:
        require(set(target) == {"analysis"}, "Layer 2 contains lifecycle or turn instructions")
        require(isinstance(target["analysis"], str) and target["analysis"], "Empty analysis target")
        publication = index[decision["publication"]]
        require(publication["kind"] == "analysis", "Invalid publication reference")
        require(publication["payload"]["analysis"] == target["analysis"], "Analysis target differs from publication")
        require(publication["payload"]["read_ms"] == decision["read_ms"], "Analysis input time differs")
        require(publication["payload"]["basis_frontend"] == current["id"], "Analysis basis differs from actual input")
        require(publication["payload"]["finished_ms"] == decision["finish_ms"], "Analysis completion time differs")


def export_corpus(corpus):
    require(corpus["schema_version"] == "parathink.pilot.v1", "Unsupported schema")
    require(len(corpus["sources"]) == 5, "The pilot must contain five independent sources")
    require(len({s["source_id"] for s in corpus["sources"]}) == 5, "Duplicate source family")
    views = {name: [] for name in MODULES}
    traces = []
    shared_checks = {}
    coverage = set()
    for source in corpus["sources"]:
        require(source["split"] == "pilot", "Pilot source used outside pilot split")
        require(len({b["branch_id"] for b in source["branches"]}) == len(source["branches"]), "Duplicate branch ID")
        for branch in source["branches"]:
            events, decisions = materialize(source, branch)
            index = {e["id"]: e for e in events}
            check_events(events, index)
            check_generation(events, decisions)
            coverage.update(branch["coverage"])
            trace_id = f'{source["source_id"]}/{branch["branch_id"]}'
            traces.append({"trace_id": trace_id, "source_id": source["source_id"], "split": "pilot", "schedule": "simulated", "events": events, "decisions": decisions})
            for decision in decisions:
                require(decision["module"] in MODULES, "Unknown module")
                model_input, current = visible_input(source, decision, index)
                check_target(decision, model_input, current, index)
                group = decision.get("shared_prefix_group")
                if group:
                    identity = (decision["module"], group)
                    value = canonical({"input": model_input, "target": decision["target"], "acceptable": decision.get("acceptable_actions")})
                    require(identity not in shared_checks or shared_checks[identity] == value, "Conflicting shared-prefix supervision")
                    shared_checks[identity] = value
                module = decision["module"]
                target_weight = 0 if decision.get("uncertain") else 1
                messages = [
                    {"role": "system", "content": PROMPTS[module], "loss_weight": 0},
                    {"role": "user", "content": canonical(model_input), "loss_weight": 0},
                    {"role": "assistant", "content": canonical(decision["target"]), "loss_weight": target_weight},
                ]
                audit = {
                    "source_id": source["source_id"], "trace_id": trace_id, "decision_id": decision["id"],
                    "read_ms": decision["read_ms"], "finish_ms": decision["finish_ms"],
                    "consumed_event_ids": decision["seen"], "frontend_snapshot": current["id"],
                    "raw_state_simulated": current["payload"]["raw_state"],
                    "label_origin": "hand_authored_prefix_candidate", "independent_review": "pending",
                    "rationale": decision["rationale"], "acceptable_actions": decision.get("acceptable_actions"),
                    "uncertain": decision.get("uncertain", False), "shared_prefix_group": group,
                    "publication": decision.get("publication"),
                }
                blockers = ["pilot_only", "independent_review_pending", "tokenizer_adapter_unimplemented"]
                if module == "soulx":
                    blockers.extend(["audio_missing", "frontend_predictions_simulated", "control_input_adapter_unimplemented"])
                if model_input["external_analysis"]:
                    blockers.append("analysis_injection_unimplemented")
                if decision.get("scope", "").startswith("future_"):
                    blockers.append("future_protocol_unimplemented")
                if decision.get("uncertain"):
                    blockers.append("uncertain_control_target")
                views[module].append({
                    "sample_id": f'{trace_id}/{decision["id"]}', "module": module,
                    "protocol_scope": decision.get("scope", "semantic_pilot"), "split": "pilot",
                    "input": model_input, "target": decision["target"], "messages": messages,
                    "loss_boundary": {"input": 0, "target": target_weight, "unit": "message_semantics_only"},
                    "eligible_for_training": False, "training_blockers": blockers, "audit": audit,
                })
    require(set(corpus["required_coverage"]) <= coverage, "Missing required coverage")
    return views, traces, sorted(coverage)


def render_review(corpus, views):
    lines = ["# 五场景与三模块 SFT 监督视图", "", "所有时间、状态与播放均为模拟。候选标签待独立审核；损失边界尚未转换为 tokenizer 标签。", ""]
    for source in corpus["sources"]:
        lines.extend([f'## {source["source_id"]}：{source["title"]}', "", source["description"], ""])
        for branch in source["branches"]:
            trace_id = f'{source["source_id"]}/{branch["branch_id"]}'
            events, _ = materialize(source, branch)
            lines.extend([f'### 分支 `{branch["branch_id"]}`', "", branch["summary"], "", "| 模拟时刻 ms | 事件 | 内容 |", "| --- | --- | --- |"])
            for event in events:
                payload = event["payload"]
                text = payload.get("transcript", payload.get("analysis", payload.get("generated_text", canonical(payload))))
                if event["kind"] == "frontend":
                    text += f'；状态 {payload["raw_state"]}；有效 complete={payload["effective_complete"]}'
                if event["kind"] == "output":
                    text += f'；阶段 {payload["phase"]}；实际听到={event.get("audit", {}).get("played_text", "（未播放）")}'
                lines.append(f'| {event["at_ms"]} | {event["kind"]} / {event["id"]} | {text.replace("|", "／")} |')
            for module in MODULES:
                samples = [v for v in views[module] if v["audit"]["trace_id"] == trace_id]
                lines.extend(["", f'**{module} 监督视图**', ""])
                if not samples:
                    lines.append("本分支没有活动思考调用，不虚构 Layer 2 生成样本。")
                for sample in samples:
                    audit = sample["audit"]
                    analysis_ids = [a["event_id"] for a in sample["input"]["external_analysis"]]
                    lines.append(f'- `{audit["decision_id"]}`：输入构造于 {audit["read_ms"]} ms；读取 `{audit["frontend_snapshot"]}`，分析 {analysis_ids or "无"}。目标 `{canonical(sample["target"])}`。{audit["rationale"]}')
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build(source_path, output_dir):
    start = time.monotonic()
    source_path, output_dir = Path(source_path), Path(output_dir)
    corpus = json.loads(source_path.read_text())
    views, traces, coverage = export_corpus(corpus)
    documents = {f"{name}_sft.json": value for name, value in views.items()}
    documents["trajectories.json"] = traces
    encoded = {name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode() for name, value in documents.items()}
    encoded["review.md"] = render_review(corpus, views).encode()
    require(sum(map(len, encoded.values())) <= 16 * 2**20, "Pilot artifacts exceed 16 MiB")
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, content in encoded.items():
        (output_dir / name).write_bytes(content)
    manifest = {
        "schema_version": corpus["schema_version"], "source_sha256": sha256(source_path),
        "generator_sha256": sha256(__file__), "independent_sources": len(corpus["sources"]),
        "derived_trajectories": len(traces), "decisions": {k: len(v) for k, v in views.items()},
        "unique_supervision": {k: len({canonical({"input": s["input"], "target": s["target"], "scope": s["protocol_scope"]}) for s in samples}) for k, samples in views.items()},
        "coverage": coverage, "all_samples_training_disabled": True,
        "audio_seconds": 0, "token_count": None, "timing_origin": "simulated",
        "source_counts": {s["source_id"]: {m: sum(v["audit"]["source_id"] == s["source_id"] for v in views[m]) for m in MODULES} for s in corpus["sources"]},
        "artifacts": {name: sha256(output_dir / name) for name in sorted(encoded)},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    execution = {
        "status": "PASS", "python": sys.version.split()[0], "python_executable": sys.executable,
        "conda_prefix": str(Path(sys.executable).parent.parent),
        "conda_history_present": (Path(sys.executable).parent.parent / "conda-meta/history").is_file(),
        "hostname": platform.node(), "elapsed_seconds": round(time.monotonic() - start, 4),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "thread_limits": {name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "output_bytes": sum(p.stat().st_size for p in output_dir.iterdir()),
        "limits": {"address_space_bytes": resource.getrlimit(resource.RLIMIT_AS)[0], "file_bytes": resource.getrlimit(resource.RLIMIT_FSIZE)[0], "cpu_seconds": resource.getrlimit(resource.RLIMIT_CPU)[0]},
    }
    (output_dir / "execution.json").write_text(json.dumps(execution, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**execution, "manifest_sha256": sha256(output_dir / "manifest.json"), "decisions": manifest["decisions"]}, ensure_ascii=False))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "datagen/scenarios.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
