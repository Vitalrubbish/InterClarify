# NTF-017：160ms 联合快照交付

2026-11-04 整理。每个 session／turn 的 160ms 批次在 SoulX 原生调用和 X2 对应两个 80ms LISTEN／DECODE 步均结束后，一次向 SharedContext 提交闭合正文、五状态与真实进度。第一帧结果只在内部暂存；WAIT 无新字也提交当前批次，保留正文原有时间。下游读取共同快照处理状态。

## 当前实现

| 文件 | 功能 |
| --- | --- |
| [SharedContext](../../../scripts/runtime/shared_context.md) | 联合事务、真实采样／身份／回执／组数／前缀校验、快照副本与话轮关闭保护 |
| [双路协调器](../../../scripts/runtime/dual_audio.md) | 当前批次有界暂存、完成后提交、提交成功后推进、失败诊断与分段计时 |
| [原生控制](../../../scripts/runtime/native_soulx.md) | 状态回调暂存，完整原生调用及设备同步结束后返回回执 |
| [独立 X2](../../../scripts/runtime/independent_x2.md) | 每 80ms 暂存真实 EOS 组及进度，正文与控制状态相互独立 |
| [架构图](../../../figures/parathink_method.md) | 单一联合写入路径，下游从共同快照进入唯一输出执行点 |

Context 每话轮仅存当前联合观察与话轮开闭状态。模型、网络、日志及消费者回调均不占 Context 锁，也不成为下一批模型推进条件。各路 available_at 保留实际完成时间，新正文与状态共享 batch_published_at。模型调用、屏障等待、提交和消费者读取分别计时。

reset 保持源采样连续，不清正文或全局步号。关闭、取消、异常、缺失／重复／过期回执或容量失败均保留上一完整观察，不释放下一步。关闭元数据写入失败时，内部有界终止标记继续拒绝迟到结果。EOF 不补 EOS 或 complete，tail_status 保持 unknown。

## 验证与边界

2026-11-03 本地交付时使用 interclarify-dev conda，全量 144 项通过、退出 0、无跳过。检查覆盖两种完成顺序、双路完成前不可见、共同发布时间、连续 WAIT、提交前禁止下一批、并发读写、关闭、迟到回调、篡改回执、容量和写入失败、reset 连续性与 EOF。原始本地日志位于 artifacts/ntf017-local/。

当前必要检查见 [Context](../../../tests/test_shared_context.md)与[双路契约](../../../tests/test_independent_frontend.md)。真实模型、完整预热和状态／正文质量见[NTF-018](../20261103-ntf018-warmup/README.md)及[NTF-019](../20261103-ntf019-fdb30/README.md)。同步完成不保证尾词齐备；LLM／TTS 接入与真实播放仍未实施。
