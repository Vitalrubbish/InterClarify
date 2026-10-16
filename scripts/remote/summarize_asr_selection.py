"""Produce a completeness-aware Chinese ASR comparison report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_asr_selection import summarize


CONFIGS = ["nemotron_en-160", "nemotron_en-560", "nemotron_multi-320", "nemotron_multi-560", "kyutai-500"]


def collect_process(run, config, repeat, sharded=False):
    """Reject missing or duplicate shard results instead of choosing one silently."""
    directories = (sorted(run.glob(f"shard-*/repeat-{repeat}/{config}")) if sharded
                   else [run / f"repeat-{repeat}" / config])
    if len(directories) != 1:
        return None, {"repeat": repeat, "exit_code": None, "reported_samples": 0,
                      "error": "missing" if not directories else "duplicate",
                      "directories": [str(d) for d in directories]}
    directory = directories[0]
    path = directory / "report.json"
    report = json.loads(path.read_text()) if path.exists() else None
    status_path = directory / "exit_code.txt"
    status = int(status_path.read_text()) if status_path.exists() else None
    return report, {"repeat": repeat, "exit_code": status,
                    "reported_samples": len(report["samples"]) if report else 0,
                    "directory": str(directory), "gpu_metadata": str(directory.parents[1] / "gpu.csv")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument("--sharded", action="store_true")
    args = parser.parse_args()
    results = {}
    for config in CONFIGS:
        rows, processes = [], []
        memory = []
        for repeat in range(args.repeats):
            report, process = collect_process(args.run, config, repeat, args.sharded)
            processes.append(process)
            if report:
                rows.extend(report["samples"])
                memory.append(report["peak_allocated_bytes"])
        complete = all(p["exit_code"] == 0 and p["reported_samples"] == args.samples for p in processes)
        results[config] = {"complete": complete, "processes": processes,
                           "summary": summarize(rows) if rows else None,
                           "peak_allocated_gib": max(memory) / 1024**3 if memory else None}
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {"run": str(args.run), "expected_samples_per_repeat": args.samples,
               "expected_repeats": args.repeats, "complete": all(r["complete"] for r in results.values()),
               "sharded": args.sharded,
               "configurations": results}
    (args.output / "comparison.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    lines = ["# 流式 ASR 同集对比", "", f"原始目录：`{args.run}`。",
             f"每配置预期 {args.samples} 条 × {args.repeats} 轮。重复轮次不是独立新音频。", "",
             "| 配置 | 完整 | 样本次 | WER | 估计逐词延迟 P50/P95 ms | 可测词/全部参考词 | 首文本 P50/P95 ms | 在线以句末标点结尾样本次 | 标点 F1 | 回写 | 峰值 GiB |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]

    def percentile_pair(value):
        if not value or value["p50"] is None:
            return "—"
        return f'{value["p50"] * 1000:.0f}/{value["p95"] * 1000:.0f}'

    for name, result in results.items():
        s = result["summary"]
        if s is None:
            lines.append(f"| {name} | 否 | 0 | — | — | — | — | — | — | — | — |")
            continue
        punctuation = "—" if s["punctuation_f1"] is None else f'{s["punctuation_f1"]:.3f}'
        lines.append(f'| {name} | {"是" if result["complete"] else "否"} | {s["samples"]} | {s["wer"]:.2%} | '
                     f'{percentile_pair(s["estimated_word_latency_seconds"])} | '
                     f'{s["estimated_word_latency_seconds"]["count"]}/{s["reference_words"]} | '
                     f'{percentile_pair(s["first_text_seconds"])} | {s["online_terminal_punctuation_samples"]} | '
                     f'{punctuation} | {s["rewrites"]} | {result["peak_allocated_gib"]:.2f} |')
    lines.extend(["", "逐词时间来自独立 CTC 强制对齐估计，缺失／低置信对齐及识别错误不填造延迟；必须结合覆盖率读数。",
                  "首文本延迟含前导静音和上下文等待。标点 F1 使用表面词边界匹配，原始 TP/FP/FN 及失败数见 JSON。",
                  "句末列只检查在线累计文本末尾为 .!?（可跟引号）；内部逗号不计，不能将此出现次数直接当作句末标点正确率。EOF 才补齐的数量在 JSON 单列。",
                  "Nemotron 为 FP32，Kyutai 为 BF16；朗读子集表现不能替代全双工自然对话回归。",
                  "标点为诊断维度，不是淘汰条件；最终结合官方 DuplexCascade 的正文回复启动行为。",
                  "任一配置缺少结果时，本表只表示当前可见证据，不表示已完成最终选型。", ""])
    (args.output / "comparison.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
