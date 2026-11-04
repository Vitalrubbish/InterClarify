# NTF-015／016：原生控制与独立 X2 交付

2026-11-04 整理。当前实现由 SoulX 原生控制、同源 PCM 账本、160ms 联合提交屏障和独立 X2 正文组成，未接入 LLM／CoT／TTS。完整合同见[前端设计](../../../dev/SoulX-Duplug/independent_streaming_frontend.md)，联合发布见[接口设计](../../../dev/SoulX-Duplug/shared_context_interface.md)。

## 实现入口

| 模块 | 功能 |
| --- | --- |
| [原生封装](../../../scripts/runtime/native_soulx.md) | 观测官方教师、KV 修订、规则、反馈和 reset，分别记录原始预测、有效状态与服务结果 |
| [冻结加载器](../../../scripts/runtime/native_soulx_loader.md) | 调用官方 TurnModel，校验源码、英文配置与本地模型资产 |
| [PCM 与屏障](../../../scripts/runtime/dual_audio.md) | 同源持续供音，分别记录真实主块、前瞻和 padding，两路完成并联合提交后推进 |
| [独立 X2](../../../scripts/runtime/independent_x2.md) | 每 80ms 执行 LISTEN／DECODE，真实 EOS 闭合组与进度交给当前批次暂存器 |

SoulX 固定源码 a0b9063843df69619b087b95b74597b2176910b8、权重 revision 61701c4ab8193cc1ee2220d3848872ac6c720142；SenseVoice revision 3847d57b6bdf2dd8875cb1508d2af43d80a16bf7。21 份源码和 21 份模型资产摘要见冻结配置。X2 revision 4c8df16、官方源码 0aca80597bb1399c0be4002de5bc62c0a779c542，使用 BF16、英语标签和 80ms 协议。

## 当前采样与生命周期

官方 startup／reset 首主块含 640 个合成采样与 1920 个真实采样，随后 640 个真实采样作为前瞻。封装保留原生内部 reset，从外部账本恢复尚未作为主块处理的音频；X2 正文、缓存和全局步号持续。真实范围分别记账，不能只凭相同步号推定对齐。

第一条 80ms 闭合组在内部暂存；每个 160ms 批次中，两路实际调用结束后一起提交正文、五状态和真实进度。失败、关闭、重复／过期回执或容量不足均保留上一完整快照。EOF 只处理存在的终止帧，右 padding 明示，尾词保持 unknown。

PCM 总量限制为 4MiB；显存、RSS、磁盘与作业时长按当前工作单限制执行。时延与积压照实记录，固定音频到达时钟不随推理减速。

## 验证

最初本地交付的 134 项检查通过，其中新增原生、加载器与双路检查共 28 项。原生 CPU 对照执行官方实际方法，以微型张量依赖核对音频／文字输入、KV 顺序、规则反馈、服务结果和 reset；该检查不代替真实权重与实时性验证。

[NTF-018](../20261103-ntf018-warmup/README.md)已完成真实权重等价性、完整预热和并发三轴 3/3；[NTF-019](../20261103-ntf019-fdb30/README.md)记录固定 FDB30 的真实结果与局限。当前行为还受[联合提交合同](../20261102-ntf017-joint-publication/README.md)约束，未切换现役 Agent。
