# `scripts/remote/summarize_tts_throughput.py`

## 功能与边界

把 `run_tts_throughput_ab_node_job.sh` 的逐 arm 产物合成一份 Markdown/JSON 对照表。只读产物（客户端 `tts_report.json` 与服务端 `[tts-metric]`/`[moss-patch]` 日志），不加载模型、只用标准库。

## 口径

- `steady_rtf = audio_seconds / (wall_seconds - first_audio_seconds)`：把一次性的会话启动与 prefill 从分母里剔除，表示**稳定态**每秒产出多少秒音频；`end_to_end_rtf = audio_seconds / wall_seconds` 也一并保留在 JSON 里。
- `service_rtf_max` / `service_rtf_median`：服务端 `[tts-metric]` 每回合 rtf 的最大值/中位数，与客户端读数互为交叉验证（客户端 wall 含投喂 pacing 与网络，服务端只覆盖生成帧）。
- `speedup_vs_baseline`：该 arm 的 warm `steady_rtf` 除以 `baseline` 的对应值。

## 输出

- `tts_throughput.md`：一张表（每 arm 一行：是否编译、cold/warm 首包、warm 音频秒与墙钟、steady rtf、服务端 rtf 最大值、相对 baseline 倍率、状态），加"说明"小节与判据。
- `tts_throughput.json`：同样的内容（含逐回合 `[tts-metric]` 明细、`patch_lines`、`fallback`/`compiled` 标记、warmup 用时），便于后续脚本消费。

状态列取值：`FAILED`（无音频）、`compile 回退`（`[moss-patch]` 出现失败/回退告警）、`compiled`（出现 `torch.compile(_local_loop) ready`）、`上游路径`。

## 用法

```bash
python scripts/remote/summarize_tts_throughput.py \
  --run-dir data/runs/tts_throughput_<tag> --report-dir reports/tts_throughput/<tag> \
  --tag <tag> [--baseline baseline]
```

节点脚本已在每个 arm 跑完后自动调用；`--baseline` 用于换参考臂。
