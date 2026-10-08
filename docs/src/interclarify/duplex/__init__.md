# `src/interclarify/duplex/__init__.py`

## 作用

P1 的 DuplexCascade 复现层入口。该包只适配**官方未修改**的推理代码（仓库内 `3rd-party/DuplexCascade`）；不实现 InterClarify 的 Layer 2 决策。

## 导出

- `DEFAULT_SCRIPT`：默认固定 micro-turn 文本脚本；
- `PromptTokens`、`build_prompt_tokens`：官方控制 token 与 ChatML 提示词查找表；
- `OfficialControlAdapter`：加载固定权重并运行脚本化 micro-turn（P1.1 离线样例）；
- `MicroTurnResult`：单个 micro-turn 的原始输出与延迟。

## 包内模块

- [official_control.md](official_control.md)（`official_control.py`）：P1.1 官方控制模型薄离线适配器；
- [official_server.md](official_server.md)（`official_server.py`）：P1.2 官方 LLM 服务的本地子进程启动器（ASR/TTS 仍是外部 Kyutai 服务；无头双工客户端见 [../realtime/__init__.md](../realtime/__init__.md)）。
