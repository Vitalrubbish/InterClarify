# MOSS 组合验证报告

`tts_combination_report.py` 读取组合 suite 的三臂原始结果、进度和退出码，复用现有阶段/图计数/token/配对函数，输出中文 Markdown 与 JSON，不运行模型或修改服务。`build` 要求三个 arm 都有完整 27 条终态，并保留预热失败；组合与 control_start 在同卡同文本/模式/轮次内配对，control_end 只用于检验漂移。

`render` 按输入模式展示首 PCM 与模拟有声时刻的均值/p50/p95、阶段均值、token 丢失/剩余和正式新图，另读独立 ASR 内容诊断。只做配置级收益判断，不把三项变化分别归因。小集合 p95 只作描述，200–300ms 目标按有声而非首 PCM 判断；没有真实设备与人工试听，不宣布产品通过。

`--run` 为远端组合目录，`--output` 为新建/本任务报告目录；`--intelligibility` 可显式提供独立 ASR summary。缺少任一终态就标未完成，不自动选择替换模型或更改在线 ASR/TTS。
