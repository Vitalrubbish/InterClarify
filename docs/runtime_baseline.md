# 已采用的运行时配置

更新：2026-10-29。本文记录已采用的运行底座与参数；具体任务配置见 `configs/`，实验结论以对应报告为准。当前目标为 SoulX-Duplug，ASR 优先适配 Nemotron EN160、条件性回退 SenseVoiceSmall，尚未替换现役控制路径，见[架构设计](research_design/architecture.md)。

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
- 现役双工控制仍由 DuplexCascade 路径执行。目标方案中 SoulX 五类用户状态送入 Layer 1，仅有效用户打断额外直接停止活动输出；普通正式回答在 Layer 1 读取对应 `user_complete` 后生成。Layer 2 的 CoT 与 Layer 0 系统附和均属后续接入。
- 控制信号与思考 token 不直接进入 TTS。
- 系统 backchannel 当前未实现，后续由 Layer 0 专项训练并接入，未从总计划移除；Layer 2 尚未接入运行链路。

参数变更须同步更新 `configs/xtalk_duplex_english_runtime.json`、`docs/configs/` 对应说明与本文。
