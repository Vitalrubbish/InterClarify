# duplex_runtime_smoke.py

## 功能、类与核心方法

在远端 conda 环境调用真实官方权重 HTTP 服务，使用当前同步的 X-Talk assembler/adapter 和真实 EventBus。阶段一验证当前已到达文本的窗口、空窗口、响应续写与协议日志；以短问题和模拟 PCM 播放确认执行链路，语义控制由真实模型产生。运行只要求协议有效与至少一段回答，记录实际 token 和时间；不强制期望模型每个窗口的语义标签。

run_smoke 注册 native TTS/coordinator/playback 与 timeline，按 0.6 秒节奏输入问题片段和空窗口，保留 full raw micro-turn 与 JSONL。NativePCM 用于模型运行时冒烟，不代替真实 ASR/MOSS 音频链路或 FDB；main 生成 report.json、失败时非零退出。报告记录当前 Python 包源码摘要，确认远端使用本地同步副本。
