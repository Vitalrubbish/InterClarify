# 2026-10-17 TTS 组件基线与修复筛选

主报告见 [中文优化报告](../../../docs/tts_latency_optimization_report.md)。本目录保留机器可读摘要、逐条离线转写及其模型/依赖清单，原始 WAV/时间线/服务日志在报告给出的远端目录。三组成对试听副本位于本地 Git 忽略的 `data/runs/tts_latency/20261017/listening/`，尚未进行人工试听。

- `tts_latency_results.json`：远端生成的统计与原始逐响应记录，210 条基线 + 99 条原筛选 + 36 条独立复测。`complete=true` 表示所有计划有终态；`all_runs_successful=false` 保留首轮 early 预热失败，不是复测未完成。
- `intelligibility_transcripts.json`：135 条转写、期望文本及编辑计数。识别失败 0，不代表所有文本均无词错误；control sparse 长句出现 3 词差异并重复观察到，具体见记录。
- `intelligibility_manifest.json`：既有 Nemotron EN 本地权重锁、模型文件 SHA256 与实际依赖版本。该 ASR 仅用于 TTS 离线内容诊断，不变更在线 ASR。
- `evidence_sha256.json`：取回时的远端摘要、当前证据与渲染器摘要，支持检查传输和文档再生成。

35 条基线文本覆盖三轮两模式。候选初筛只用短答、澄清和长句三条，每模式三轮；135 条音频记录只有 20 个不同 WAV，不能外推正式自然度或可靠尾延迟。首轮 early 的失败和修复后 36 条同卡配对分别保留，不跨 GPU 借用 control。具体作业 ID 与源码提交见任务单。

主 Markdown 由保存的 JSON 与 `scripts/remote/tts_latency_report.py` 的 `render_markdown` 渲染；JSON 的远端取回 SHA256 为 `20768055ccd9e3be2ecbe07a5e4ef804d9e1fc5d8dce4de7f57141644032f90a`。报告中的 `/mnt/cloudstorfs/...` 是远端共享路径经 `Path.resolve` 解析后的形式，任务单通常使用 `/hpc_stor03/...` 别名。
