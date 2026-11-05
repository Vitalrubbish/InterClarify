# SoulX-Duplug 路线

更新：2026-11-05。第一阶段 ASR-Frontend 已收口，当前唯一路线为 **SoulX-Duplug 官方配置＋并行 X2Streaming-ASR**。

## 1. 路线定义

- SoulX 使用官方子模块固定提交，保留内部 SenseVoice 教师、文字门控、窗口识别、KV 修订、状态规则、反馈和原生 reset。
- 独立 X2 接收同一份持续 PCM，以 80ms 原生步执行 LISTEN／DECODE，按 EOS 闭合完整词，只向 SharedContext 提供正文。
- 每 160ms 调度批次内，X2 完成两个 80ms 步、SoulX 完成本步原生调用后，正文、五状态和真实进度一次写入 SharedContext；提交成功才释放下一周期。
- 外接正文不注入 SoulX 状态 KV，内部文字只作控制与诊断；控制器 reset 不清空正文或全局步号。

完整合同见[独立流式前端](independent_streaming_frontend.md)，Context 字段见[联合快照接口](shared_context_interface.md)，运行资产见[部署说明](deployment.md)。

提前 complete 的实测案例、官方运行时取消与历史整理，以及对 Layer 1／2 和播放闭环的影响，见[行为与运行时分析](completion_runtime_analysis.md)。该分析不表示下游运行时已接入。

## 2. 当前状态

| 工作单 | 交付 |
| --- | --- |
| [NTF-015／016](../../reports/soulx/20261102-native-independent-frontend/README.md) | 原生控制封装、同源 PCM、160ms 屏障和独立 X2 适配 |
| [NTF-017](../../reports/soulx/20261102-ntf017-joint-publication/README.md) | 文本／状态／进度联合提交，移除前端停止旁路 |
| [NTF-018](../../reports/soulx/20261103-ntf018-warmup/README.md) | 完整预热、真实权重对照和并发三轴 3/3 |
| [NTF-019](../../reports/soulx/20261103-ntf019-fdb30/README.md) | 固定 FDB30 验收，用户审核通过并归档 |
| [NTF-030](../../reports/soulx/20261103-latency-limit-removal/README.md) | 取消 800ms 时长停止条件，保留容量与资源保护 |

独立半双工 LLM／TTS [首轮评测](../../reports/soulx/20261105-fdb30-half-duplex/README.md)已完成；执行线程及 complete 重识别修复后的完整复测由 [NTF-054](../../issue/NTF-054.md) 跟踪。Layer 1 训练、CoT 注入及现役 Agent 切换尚未实施。

## 3. 实现入口

| 模块 | 位置 |
| --- | --- |
| 原生控制封装 | [native_soulx](../../scripts/runtime/native_soulx.md) |
| 官方模型加载 | [native_soulx_loader](../../scripts/runtime/native_soulx_loader.md) |
| 独立 X2 适配 | [independent_x2](../../scripts/runtime/independent_x2.md) |
| 同源 PCM 与 160ms 屏障 | [dual_audio](../../scripts/runtime/dual_audio.md) |
| 联合快照存储 | [shared_context](../../scripts/runtime/shared_context.md) |
| 远端探针 | [native_frontend_probe](../../scripts/remote/native_frontend_probe.md) |
| X2 隔离执行器 | [native_frontend_worker](../../scripts/remote/native_frontend_worker.md) |
| X2 单路探针 | [x2_streaming_probe](../../scripts/remote/x2_streaming_probe.md) |

## 4. 边界

- 两路读取同一份 16kHz 单声道 float32 PCM，不因某一路更慢而减速送音、跳帧或读取未来音频。
- 已提交正文只追加、不回改；子词草稿不进入 Context，EOS 只闭合发射组，不代表用户话轮结束。
- 已提交的有效 `user_complete` 携当前正文直接供下游使用；同步完成不保证尾词必齐。
- 延迟、未读 PCM、墙钟积压和发布延迟照实记录；4MiB PCM、显存、RSS、磁盘和作业时长上限继续有效。
- 独立半双工评测已实现 complete／nonidle 消费、去重、取消及播放实录；其结果不能代表 Layer 1／thinking 或现役 Agent 已接入。
