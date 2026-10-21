# 已采用的运行时配置

更新：2026-10-21。本文固定当前运行底座与已采用的组件、生成和播放参数；具体任务配置见 `configs/`，实验结论以对应报告为准。

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
- Layer 0 输出基础话轮控制 token，Layer 1 负责表达与思考请求，Layer 2 异步返回结构化结果。
- 控制信号与思考 token 不直接进入 TTS。
- 系统 backchannel 当前关闭；Layer 2 尚未接入运行链路。

参数变更须同步更新 `configs/xtalk_duplex_english_runtime.json`、`docs/configs/` 对应说明与本文。
