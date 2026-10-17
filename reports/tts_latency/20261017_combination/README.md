# MOSS 组合验证证据

主报告：[组合验证](../../../docs/tts_combination_validation.md)。本目录包含 `tts_combination_results.json`（三组各27条及阶段/token/图计数/配对结果）、`intelligibility_transcripts.json`（81条离线转写）、识别模型清单及校验摘要。正式运行与内容作业都已结束，无运行失败；16个不同WAV不能当作81个独立语音样本。

运行源码 `6c59aa3`，TTS作业 `job-179224493766087164069-xuan-zhang`，内容诊断作业 `job-179224676434988761253-xuan-zhang`。固定MOSS/adapter/权重/音色/采样与上一轮一致；只在同卡组合与control内部配对，不与历史另一分配卡相减。

原始WAV/trace/log位于远端 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-tts-runs/20261017-combination-01`；本地JSON经SFTP取回并核验SHA256。报告可由保存JSON和 `scripts/remote/tts_combination_report.py` 的 `render` 再生成。

观察到收益不等于200–300ms有声目标已达；人工自然度、真实播放和FDB未验收。在线ASR/TTS与产品默认值均未替换。
