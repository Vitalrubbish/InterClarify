# 工程实施计划

更新：2026-11-02。用户要求归档当前活跃issue，先调研SenseVoice／X2教师接入与状态退化。原NTF-015—020均为未实施归档，见[归档记录](reports/soulx/20261102-frontend-plan-archive/README.md)。当前为[NTF-021—025](issue/README.md)，本轮仅归档与建单，没有实现或提交远端作业。研究范围见[研究方案](research_design.md)，详细合同见[调研方案](dev/SoulX-Duplug/asr_teacher_diagnosis.md)。

## 1. 当前目标与运行底座

先核查官方教师协议与训练分块时标，再对同一音频测量两种ASR的出词、修订／闭合、教师消费及墙钟时间。从原生SenseVoice建立干净基线，尽量保持门控、差分／KV修订、状态规则、反馈和reset接入X2；明确不可避免的协议差异，再通过单因素消融定位退化原因。

现役底座仍为X-Talk ca9b23c、DuplexCascade、Nemotron EN160与Kokoro，见[运行配置](runtime_baseline.md)。本轮不切换Agent；官方源码使用[子模块和远端独立checkout](third_party/soulx-duplug.md)，不恢复已退役comparison加载器。既有实现和历史通过记录不替代新对照。

## 2. 调研顺序与交付

| 顺序 | 工作单 | 交付与进入下一步的条件 |
| --- | --- | --- |
| 1 | [NTF-021](issue/NTF-021.md) | 协议／训练时标核查、公开资料缺口、冻结输入与采集／预热合同，以及前两项实验预算 |
| 2 | [NTF-022](issue/NTF-022.md) | 固定6条的独立ASR词级时间轴，区分首次出现、修订、EOS闭合和计算时间 |
| 3 | [NTF-023](issue/NTF-023.md) | 原生采集等价性、最小X2适配diff及6条完整状态轨迹；正确性与实时预检通过 |
| 4 | [NTF-024](issue/NTF-024.md) | 两ASR内规则开／关完整重放，固定因果文字的提交延迟消融，明确有效归因与限制 |
| 5 | [NTF-025](issue/NTF-025.md) | 原固定FDB30复核原生／最小替换臂，必要时加一条预先冻结消融臂，形成路线建议 |

小样本包括接话ID102／3、停顿ID127、打断ID136／20／9，均来自原FDB30。每次对照使用完全相同PCM，不因结果换样本。状态按标注及事件核查评价，r6与SenseVoice都不是绝对状态真值。正式30条不做显著性承诺，失败、识别覆盖、原始与规则改写状态全部报告。

ASR独立时间测量与控制器门控后的实际消费分开。延后同一个complete的发布不是状态预测改善；强制对齐和完整后续音频仅作离线评分，不能让在线教师提前看到未来词。门控、修订或reset无法等价时先补设计，不能将多项改造解释为单纯换ASR。

## 3. 资源与实施边界

本地使用既有conda完成必要轻量检查，真实模型只在远端conda调度作业运行。复用已有权重、环境和数据，每个实现文件同步维护docs同路径中文说明，包含整体功能、类设计和核心方法。

远端单活动作业、1×4090、4CPU、32GiB RAM、batch=1、显存22GiB停止线；每模型worker至多1、CPU线程各≤2。每作业≤1800秒、输出≤128MiB、启动空闲磁盘≥10GiB。每路未读PCM≤800ms、总PCM≤4MiB，在线送音迟到和发布延迟沿用800ms停止线，不靠慢速送音或丢帧达标。

预热覆盖真实语音、多种窗口长度、修订与完成分支，以及X2首块／增量、WAIT／DECODE／EOS；就绪后清理会话、重置种子再启动正式时钟。离线因果重放单独标记，不能用其加速吞吐充当在线延迟。

NTF-021冻结NTF-022／023有限矩阵与总预算；NTF-024和NTF-025各自在实施前冻结实验臂、作业数、累计GPU时长及结果预算。原NTF-018／019额度随归档失效，不自动转用。前置预检未过不启动正式30条，不自动扩容、换卡、调阈值或筛选重跑。本轮不启动推理／训练、不接LLM／CoT／TTS。

## 4. 已归档方案与后续研究

[原生控制＋独立X2正文](dev/SoulX-Duplug/independent_streaming_frontend.md)及[SharedContext接口](dev/SoulX-Duplug/shared_context_interface.md)保留为候选设计。正文／状态独立更新、仅complete交接、续说取消、去重和超时均未实现；是否采用等待新调研结论，原工作单不自动恢复。

已确认的下游分工、普通回答生成边界、有效nonidle直接停止、单一输出执行点与TTS播放所有权保留。CoT条件化控制仍是后续研究目标，见[架构第2.5节](research_design/architecture.md#25-soulx-的-cot-条件化控制)；本次不构造训练数据或更新参数。图源改造随旧接口工作归档，当前不改图。

历史证据包括[X2教师30/30](reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)、[协议差异归因](reports/soulx/20261101-ntf012-x2-teacher-fdb30/regression_analysis.md)、[Nemotron教师](../reports/soulx/20261101-ntf009-teacher-fdb30/README.md)及[双ASR配对](../reports/soulx/20261031-dual-asr-publication/README.md)。原始证据保持，不作为当前方案已经验证的依据。

TextTurn、VoxTurn、XTurnix已归档，见[归档区](archive/dev/README.md)、[实现归档](../archive/README.md)和[报告](../reports/README.md)。历史issue保存在本地docs/issue/archive/，不新增跟踪；旧训练与全量benchmark不恢复。
