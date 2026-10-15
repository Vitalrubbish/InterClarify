# `scripts/remote/summarize_tts_throughput.py`

## 功能与边界

把 `run_tts_throughput_ab_node_job.sh` 的逐 arm 产物合成一份 Markdown/JSON 对照表。只读产物（客户端 `tts_report.json` 与服务端 `[tts-metric]`/`[moss-patch]` 日志），不加载模型、只用标准库。

## 口径

- `steady_rtf = audio_seconds / (wall_seconds - first_audio_seconds)`：把一次性的会话启动与 prefill 从分母里剔除，表示**稳定态**每秒产出多少秒音频；`end_to_end_rtf = audio_seconds / wall_seconds` 也一并保留在 JSON 里。
- `service_rtf` / `service_rtf_median`：服务端 `[tts-metric]` 的 `Σaudio_s / Σwall_s` 与逐行 rtf 的中位数。每行只统计"自上一行以来"的切片，所以必须**求和**；中位数用于排除首行（含编译/warmup）的影响。与客户端读数互为交叉验证。
- `local_share` / `backbone_share`：该 arm 全部行里 CUDA event 累计的"本地码本循环"/"backbone 前向"秒数 ÷ 累计墙钟，用来判断时间花在哪一侧。
- `engaged`：日志是否出现 `compiled path engaged`，即编译路径**真的被推理用到**（而不是只建好了图）。
- 编译臂的读数口径：客户端 `steady_rtf` 把"会话内的首次编译"算进了分母，会严重偏低（实测 `t1-sdpa-cudagraph` 客户端 0.44 而稳态切片 2.18），因此编译臂要看**服务端 rtf/中位数**；`warm` 若是该服务进程的第一个会话，则编译成本也落在这一列里。
- `profile`：从 `[moss-patch] profile frames=… device_s=… cpu_s=… top=…` 行解析出的单回合剖析结果（device 合计、cpu 合计、最重的 3 个 kernel 及调用次数）。
- `speedup_vs_baseline`：该 arm 的 warm `steady_rtf` 除以 `baseline` 的对应值。

## 输出

- `tts_throughput.md`：一张表（每 arm 一行：是否编译、是否生效、cold/warm 首包、warm 音频秒与墙钟、steady rtf、服务端 rtf 与中位数、local/backbone 占比、相对 baseline 倍率、状态），加"说明"小节与判据；有剖析数据的 arm 另出一张 **profile 表**（剖析帧数、device/cpu 合计、device/帧、top kernel），用来判断"每帧还有多少时间在等 CPU"，并点名 `metrics/<arm>.profile.txt` 的完整 kernel 表。
- `tts_throughput.json`：同样的内容（含逐行 `[tts-metric]` 明细、`patch_lines`、`fallback`/`compiled`/`engaged` 标记、warmup 用时、`profile_file`），便于后续脚本消费。

状态列取值：`FAILED`（无音频）、`compile 回退`（出现失败/回退告警）、`编译未生效`（图建好但没有 `compiled path engaged`）、`compiled`、`上游路径`。

## 用法

```bash
python scripts/remote/summarize_tts_throughput.py \
  --run-dir data/runs/tts_throughput_<tag> --report-dir reports/tts_throughput/<tag> \
  --tag <tag> [--baseline baseline]
```

节点脚本已在每个 arm 跑完后自动调用；`--baseline` 用于换参考臂。
