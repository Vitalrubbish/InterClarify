# 工程实施计划

更新：2026-11-02。用户确认[原生SoulX控制＋独立X2整词正文](dev/SoulX-Duplug/independent_streaming_frontend.md)，并补充只有complete交接等待独立解码。当前工作单为NTF-015—020，执行顺序见下表；本轮仅设计与建单，尚未实现或启动远端作业。范围见[研究方案](research_design.md)，下游边界见[架构](research_design/architecture.md)。

## 1. 当前目标与运行底座

目标前端位于Layer 0–Layer 2输入侧。SoulX内部保留SenseVoice教师、文字门控、窗口修订、状态反馈及原生reset；按用户指定，X2Streaming-ASR独立持续解码，只在EOS闭合组后以完整词追加共享正文，不暴露组内子词，不向SoulX注入外部教师文字。两路接收同一PCM，各自就绪即更新Context，不等待逐块配齐。

现役底座仍为X-Talk ca9b23c、DuplexCascade、Nemotron EN160与Kokoro，见[运行配置](runtime_baseline.md)。本轮不切换现役Agent；官方源码使用[本地子模块和远端独立checkout](third_party/soulx-duplug.md)，不恢复已退役comparison加载器。

| 模块 | 当前设计职责 |
| --- | --- |
| SoulX原生控制 | 保留内部教师协议和五状态，提供实际输入／状态来源及时间边界 |
| 独立X2Streaming-ASR | 复用锁定4B模型、BF16与原生80ms自适应缓存，EOS闭合后按完整词追加正文 |
| SharedContext | 正文／原始状态／实际解码进度分别更新，短锁原子合并，保存至多一条当前complete交接记录 |
| complete交接同步 | 原始complete固定目标，X2真实追齐并提交闭合组后ready；支持续说取消、去重与有界超时，不阻塞两路 |
| Layer 1 | 读取即时正文及四类非complete状态，实际读到交接ready的complete后于当前turn开始普通回答，同ID去重 |
| 输出运行时 | 有效nonidle直接提交唯一停止执行点；其他状态不映射start／keep |
| Layer 2／Layer 0 | CoT思考与系统附和属于后续接入，本轮不实现 |

控制器reset不结束ASR、不清空正文、交接记录或重开逻辑话轮。原始complete立即记录，仅用于回答的complete等待对应解码与已闭合正文；ready不保证所有尾词已发射。原有无complete保留约束改为至多一条当前交接记录，不建历史队列或新语义判断模型。生成、停止、实际播放与已听内容的既有边界保持。

## 2. 实施顺序与门槛

| 顺序 | 工作单 | 交付与进入下一步的条件 |
| --- | --- | --- |
| 1 | [NTF-015](issue/NTF-015.md) | 原生控制封装与reset／采样账本审计；不套用旧教师和buffer写回补丁 |
| 2 | [NTF-016](issue/NTF-016.md) | 同源PCM分发、X2原生80ms解码与EOS完整词提交，无跨路屏障或旧教师两帧聚合 |
| 3 | [NTF-017](issue/NTF-017.md) | 异步字段合并、原子快照、关闭与迟到处理，必要契约检查通过 |
| 4 | [NTF-020](issue/NTF-020.md) | 仅complete的交接同步、取消、去重与超时，必要契约检查通过 |
| 5 | [NTF-018](issue/NTF-018.md) | 完整预热及有限预热对照，含交接路径；双路三轴3/3完整、无过载才进入正式验收 |
| 6 | [NTF-019](issue/NTF-019.md) | 固定FDB30单路／双路对照，原始状态与ready交接分开报告；30/30、退出0、无过载为实时门槛 |

预热不足作为优先排查假设：历史双ASR缺少完整非静音、多长度预热。新预热须覆盖真实语音触发的内部ASR、多个窗口／整轮长度、修订、完成分支及独立流式解码；预热会话与正式输入隔离，全部就绪后才启动到达时钟。分别报告首遇路径与稳定阶段的排队、计算和发布，不预先把全部积压归因于预热，也不为通过而放慢送音或去掉首帧。

新链路当前只完成设计。历史接口、教师实验和六视图检查不能替代以上验收；真实模型只在远端conda受限调度作业执行，本地仅做必要轻量契约检查。每个实现文件同步维护docs同路径中文说明，包含功能、类设计与核心方法。

## 3. 资源与执行边界

远端根目录为~/parathink-soulx-duplug/，只读复用既有权重、conda和数据，见[目录约定](remote_workspace.md)。单并发作业、1×4090、4CPU、32GiB RAM、batch=1，显存停止线22GiB；每路模型worker各1、CPU线程各≤2，不启动无界worker池。

每路未读真实PCM≤800ms，送音迟到及各路在线发布延迟执行800ms过载停止线，PCM总量≤4MiB。各路发布延迟分别按真实主块／解码范围和完整观察边界报告；800ms是保护上限，不是交互质量目标。Context容量沿用既有限额，不以无界队列隐藏慢路。

complete首轮等待上限为800ms，deadline还受原始complete主块截止到ready的既有800ms总延迟线约束，取更早者，不追加预算。等待非阻塞，重复complete不续期，有效nonidle续说与incomplete撤销旧交接；超时验证失败，不以旧正文或半词强行放行。

NTF-018最多2个串行作业，NTF-019最多2个串行作业；每作业≤1800秒、结果≤128MiB，累计GPU预算≤2小时、结果≤512MiB，启动空闲磁盘≥10GiB。不复制权重，不自动重复实验、换卡、扩容或提高停止线。预检未过则不启动正式30条，失败与未通过结论照实保留。

用户本轮要求设计与建单，以上是后续实施合同，当前不提交GPU任务、不训练，也不接下游LLM／CoT／TTS。

## 4. 后续研究与历史证据

SoulX联合音频、转写与已发布CoT的条件化控制仍是后续研究目标；其序列、缓存、触发与训练另行设计，见[架构第2.5节](research_design/architecture.md#25-soulx-的-cot-条件化控制)。Layer 1表达与思考调用、Layer 2分析和Layer 0附和专项按既有研究范围推进，不因本轮前端建单自动实施。

历史Nemotron／X2教师前端与双ASR配对发布保留报告：[双ASR18/30及预热差异](../reports/soulx/20261031-dual-asr-publication/README.md)、[Nemotron教师30/30](../reports/soulx/20261101-ntf009-teacher-fdb30/README.md)、[X2教师30/30](reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)、[协议差异归因](reports/soulx/20261101-ntf012-x2-teacher-fdb30/regression_analysis.md)。这些实验未证明新方案已通过，也不作为绝对状态真值。

TextTurn、VoxTurn、XTurnix已归档，入口见[归档区](archive/dev/README.md)、[实现归档](../archive/README.md)和[报告](../reports/README.md)。历史工作单保留在本地docs/issue/archive/，不进入Git；旧训练、全量benchmark和comparison实验不自动恢复。
