# SoulX-Duplug 路线

更新：2026-11-07。当前前端为 SoulX-Duplug 原生控制＋独立 X2Streaming-ASR，独立半双工评测已完成首轮，修复后完整复测由 [NTF-054](../../issue/NTF-054.md) 跟踪。

## 1. 分工与边界

SoulX 保留原生 SenseVoice 教师、状态规则、反馈及 reset；X2 以 80ms 原生步解码完整词，只向 SharedContext 提供正文。两路读取同源 PCM，每 160ms 完成后联合提交正文、五状态和实际进度，提交成功才释放下一批。外接正文不写入 SoulX 状态 KV，内部 reset 不清空 X2 正文。

已提交的有效 complete 携当前正文供下游使用，同步不保证尾词齐备。普通半双工评测已实现状态消费、去重、取消和播放实录；Layer 1 持久 Context、Layer 2 结果注入、专项训练与 X-Talk 常驻集成尚未实施。

## 2. 设计与运行入口

| 内容 | 说明 |
| --- | --- |
| [独立前端](independent_streaming_frontend.md) | 模型分工、160ms 屏障与前端合同 |
| [SharedContext 接口](shared_context_interface.md) | 最新联合快照、字段与消费边界 |
| [部署资产](deployment.md) | 固定源码、模型与 conda |
| [完整半双工方案](fdb30_half_duplex.md) | 当前 LLM／TTS 评测及资源约束 |
| [运行基线](../../runtime_baseline.md) | 当前配置、保留工具与清理范围 |
| [Layer 1 协议](../layer1/protocol.md) | 后续表达、持久上下文及首音前后取消 |
| [Layer 2 协议](../layer2/protocol.md) | 后续冻结思考层与最终结果交付 |

## 3. 实现说明

| 模块 | 文档 |
| --- | --- |
| 原生控制与模型加载 | [native_soulx](../../scripts/runtime/native_soulx.md)、[loader](../../scripts/runtime/native_soulx_loader.md) |
| 独立 X2 与同源调度 | [independent_x2](../../scripts/runtime/independent_x2.md)、[dual_audio](../../scripts/runtime/dual_audio.md) |
| 联合快照 | [shared_context](../../scripts/runtime/shared_context.md) |
| 通用前端诊断 | [probe](../../scripts/remote/native_frontend_probe.md)、[X2 worker](../../scripts/remote/native_frontend_worker.md)、[X2 探针](../../scripts/remote/x2_streaming_probe.md) |

旧前端独立验收和早期分析已退出当前入口，历史内容通过 Git 追溯；当前首轮评测与活动复测见[报告索引](../../../reports/README.md)。
