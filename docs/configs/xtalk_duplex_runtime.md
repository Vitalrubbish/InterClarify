# xtalk_duplex_runtime.json

## 作用与配置

Xtalk.from_config 可直接读取的阶段 A 官方模型配置。保留 Qwen3 ASR 与 MOSS TTS，开启 duplex_enabled，DuplexRuntimeAdapter 经 8006 端口连接官方权重推理服务。LLM 通过结构化 micro-turn 历史的 HTTP 接口独立接入（服务端展平为 raw ChatML），配置不创建 DefaultAgent 或 TurnSense 语义控制链路。

duplex_micro_turn_seconds 默认 0.6；duplex_max_new_tokens 默认 64，沿用官方值；duplex_timeout_seconds 为服务失败边界；duplex_timeline_dir 指向会话 JSONL。使用布尔 true，禁止浮动字符串开关。ASR/TTS 地址和参考音色路径可由远端任务生成覆盖；原生连接配置 xtalk_round1_runtime.json 保留作对照。

## 启动条件

先在远端 conda 启动 ASR、官方权重服务和 MOSS，确认 /health。源码使用 X-Talk dev 当前实现；manifest 固定实际提交或未提交工作树摘要，不能宣称已有提交哈希包含工作树补丁。此前 d9303c8 的连接结果只代表原生链路，不替代本配置验收。
