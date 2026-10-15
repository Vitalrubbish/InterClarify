# xtalk_duplex_runtime.json

## 作用与配置

Xtalk.from_config 可直接读取的阶段 A 官方模型配置。保留 Qwen3 ASR 与 MOSS TTS，开启 duplex_enabled，DuplexRuntimeAdapter 经 8006 端口连接官方权重推理服务。LLM 通过结构化 micro-turn 历史的 HTTP 接口独立接入（服务端展平为 raw ChatML），配置不创建 DefaultAgent 或 TurnSense 语义控制链路。

**依赖（2026-10-15）**：这份配置要求运行时进程所在环境装有 `onnxruntime`（由 `xtalk[silero-vad]` extra 提供）；镜像 `round1:v0.3` 的 client 环境没有，构造 VAD 会抛 `RuntimeError` 并让回放服务起不来，镜像从 **v0.4** 起补上并钉 `onnxruntime==1.31.0`（与本机 client 环境同版本，离线取自 wheelhouse）。

**`vad` 槽位（2026-10-15 新增）**：注册 `SileroVAD`（ONNX Runtime，模型取 `~/.cache/xtalk/models/silero_vad.onnx`，已在共享盘缓存）。这一步是必须的：`VADManager` 只在"配置了后端 VAD 模型"时工作（`models.get(VAD)` 为 None 时它整条逻辑直接 return），缺了它就只剩 input gateway 在**音频流边界**代发的 `vad_speech_end`——FDB 里自带尾部静音供回答的样本会被拖到文件结束才释放用户文本（实测 `synthetic_user_interruption/101`：语音 13.0s 结束、文本 ~11.6s 已完整，停顿边界却到 27.1s 才发）。`service_config.vad_redemption_ms` 设为 **600**，与 ASR 的 `chunk_ms: 600` 对齐：停顿判定不能早于"最后一段语音已交给 ASR"的那一刻，否则句尾会被留在 1s 预缓冲里等下一次语音开始。

duplex_micro_turn_seconds 默认 0.6；duplex_max_new_tokens 默认 64，沿用官方值；duplex_timeout_seconds 为服务失败边界；duplex_timeline_dir 指向会话 JSONL。使用布尔 true，禁止浮动字符串开关。ASR/TTS 地址和参考音色路径可由远端任务生成覆盖；原生连接配置 xtalk_round1_runtime.json 保留作对照。

## 启动条件

先在远端 conda 启动 ASR、官方权重服务和 MOSS，确认 /health。源码使用 X-Talk dev 当前实现；manifest 固定实际提交或未提交工作树摘要，不能宣称已有提交哈希包含工作树补丁。此前 d9303c8 的连接结果只代表原生链路，不替代本配置验收。
