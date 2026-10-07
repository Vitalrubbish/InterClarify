# `src/interclarify/duplex/__init__.py`

## 作用

P1 的 DuplexCascade 复现层入口。该包只适配**官方未修改**的推理代码（仓库内 `3rd-party/DuplexCascade`），用于离线注入固定输入；不实现 InterClarify 的 Layer 2 决策。

## 导出

- `DEFAULT_SCRIPT`：默认固定 micro-turn 文本脚本；
- `PromptTokens`、`build_prompt_tokens`：官方控制 token 与 ChatML 提示词查找表；
- `OfficialControlAdapter`：加载固定权重并运行脚本化 micro-turn；
- `MicroTurnResult`：单个 micro-turn 的原始输出与延迟。

实时 ASR/TTS 服务不属于本包，属于 P1.2。
