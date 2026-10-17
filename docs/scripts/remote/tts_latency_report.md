# TTS 延迟报告生成器

`tts_latency_report.py` 使用标准库读取原基线与同卡筛选结果，生成中文 Markdown 和 JSON 摘要，不调用模型、不修改运行时。`summarize_run` 按输入模式、轮次和文本汇总首 PCM、波形有声估计、倍率与模拟欠载；失败/无音频保留分母，正式响应与预热按 ID 分开。

`trace_checks` 在同一进程/响应内核对 token 接收、实际消费、结束余量，提取 worker 接受文本至 prefill 的门槛等待、前 1/5/10/50 帧耗时和 Dynamo 图增量。没有事件时标为缺测，不能把缺测当通过；token 完整性不代表语音无漏词。`compare_runs` 只比较相同文本/模式/轮次，batch4 另核对 PCM SHA256；prefill 候选改变条件，不要求其音频与 control 相同。

`build_report` 记录作业完成标志、源码、GPU、配置和日志诊断，按候选列出收益与失败。未完成的 arm 标为待完成，不把局部结果写成最终验收；即使指标改善，也保留人工试听、真实播放器和 FDB 未验收的边界。`render_markdown` 生成完整报告，不从已有模板填入假定收益。

CLI 为 `--baseline` 原基线根、`--screen` 同卡筛选根、`--output` 报告目录。输出 `tts_latency_optimization_report.md` 与 `tts_latency_results.json`，可重复生成本任务报告；原始 WAV/JSONL 保留在远端对应 run 根。报告仅使用可复核文件，不依赖日志里自称“通过”。
