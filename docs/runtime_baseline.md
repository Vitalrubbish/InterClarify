# 已采用的运行时配置

更新：2026-11-03。本文记录现役 Agent 的运行时底座与参数；ASR 前端验收路线为[SoulX 原生控制＋独立 X2 正文](dev/SoulX-Duplug/independent_streaming_frontend.md)，其 015／016／017 已本地交付，018 真实权重预检和 019 固定 FDB30 验收已归档；030 取消前端 800ms 时长停止条件。后续 LLM 接入暂缓，尚未替换下述现役控制路径。已有远端资产见[部署说明](dev/SoulX-Duplug/deployment.md)，下游目标见[架构设计](research_design/architecture.md)。

## 组件

| 模块 | 采用值 |
| --- | --- |
| 运行底座 | X-Talk fork，提交 `ca9b23c`（`dev`） |
| ASR | Nemotron EN 0.6B，流式 160ms 分块，音频传输 80ms |
| TTS | Kokoro 82M，音色 `af_heart` |
| 语言模型 | DuplexCascade 官方权重，Qwen2-7B-Instruct 基座 |
| 推理精度 | BF16；真实模型仅在远端 GPU 加载 |

## 时序与缓存

| 参数 | 采用值 |
| --- | --- |
| micro-turn | 600ms |
| TTS 首段 | 300ms |
| TTS 后续分段 | 1200ms |
| 跨请求缓存 | 按会话复用 KV，缓存内容以完整历史与原始生成 ID 为事实来源 |
| 生成策略 | `duplex_greedy_v1`：greedy、单 beam、`repetition_penalty=1.0`，不继承模型目录采样参数 |

## 行为边界

- 保持单一仲裁器与单一 TTS 播放所有权；已播放内容不可撤销。
- 现役双工控制仍由DuplexCascade执行。目标方案中五状态及正文在每160ms双路完成后联合提交；Layer 1在正常输入边界读到有效complete及当前正文后可在当前turn回答，无额外交接等待。下游从共同快照读取有效nonidle后，由唯一输出运行时处理停止；消费去重留待下游接入。Layer 2 CoT与Layer 0系统附和仍为后续接入。
- 控制信号与思考 token 不直接进入 TTS。
- 系统 backchannel 当前未实现，后续由 Layer 0 专项训练并接入，未从总计划移除；Layer 2 尚未接入运行链路。

参数变更须同步更新 `configs/xtalk_duplex_english_runtime.json`、`docs/configs/` 对应说明与本文。
