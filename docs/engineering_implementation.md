# 工程实施计划

更新：2026-11-03。当前路线为原生SoulX＋SenseVoice控制、独立X2完整词正文、160ms双路联合提交。015／016／017本地交付和018真实权重预检已归档；[019](reports/soulx/20261103-ntf019-fdb30/README.md)按用户审核决定通过并归档，历史29/30、退出1及单路缺失保留。[030](reports/soulx/20261103-latency-limit-removal/README.md)已按指令取消800ms停止条件，保留容量与作业资源上限。后续LLM接入按用户最新指令暂缓，031—035草案未实施归档。

## 1. 当前目标与运行底座

SoulX保留内部SenseVoice教师、门控、滑窗差分／KV修订、状态规则、反馈和原生reset；X2只为共享上下文提供独立正文，不将外接转写注入状态KV。两路读取同一持续PCM。每160ms批次等X2完成两个80ms原生步及其组内解码、SoulX完成本步原生调用后，将EOS闭合正文和状态token一次写入SharedContext；提交成功后才允许下一步。先完成结果只在内部暂存，不写原始PCM。

五状态统一经过本批次联合提交，不设置前端nonidle专用停止钩子。当前冻结采样映射下，X2本批次实际处理覆盖SoulX状态观察截止，DECODE闭合和正文提交由联合事务完成。已提交的有效complete携当前正文直接供Layer 1在当前turn使用，无需额外交接等待；同步不保证尾词必齐。详细合同见[独立前端](dev/SoulX-Duplug/independent_streaming_frontend.md)及[Context接口](dev/SoulX-Duplug/shared_context_interface.md)。

现役底座仍见[运行配置](runtime_baseline.md)，本次不切换Agent。官方源码使用[固定子模块及远端checkout](third_party/soulx-duplug.md)，不恢复已退役comparison加载器。历史教师替换和双ASR实验只作证据，不代替新封装的输入／reset等价性验证。

## 2. 工作顺序与交付

| 顺序 | 工作单 | 交付与进入下一步的条件 |
| --- | --- | --- |
| 1 | [NTF-015](reports/soulx/20261102-native-independent-frontend/README.md) | 已完成：原生协议控制封装、冻结加载器、状态来源与reset审计 |
| 2 | [NTF-016](reports/soulx/20261102-native-independent-frontend/README.md) | 已完成：同源PCM、X2原生80ms适配、160ms屏障、EOS正文／真实进度回调 |
| 3 | [NTF-017](reports/soulx/20261102-ntf017-joint-publication/README.md) | 已完成联合提交、停止旁路撤回、短锁生命周期和图源同步，本地144项检查通过 |
| 4 | [NTF-018](reports/soulx/20261103-ntf018-warmup/README.md) | 同一拓扑完整预热、有限预热对照和单路参考；预检3/3完整、退出0且无800ms过载 |
| 5 | [NTF-019](reports/soulx/20261103-ntf019-fdb30/README.md) | 已由用户审核通过并归档，原始运行与限制保留 |
| 6 | [NTF-030](reports/soulx/20261103-latency-limit-removal/README.md) | 已取消原生单／双路及分析的800ms停止条件，169项本地检查通过 |

015—019前端工作已收口，020取消；031—035未实施归档，无活动接入任务。两路每批联合写Context后推进，不等待消费者；原生reset不清正文，生产者持续到达，所有时标与EOF尾部独立报告。首段是否已有实际播出采样的分段合同保留，当前不实施下游。

## 3. 资源与执行边界

本地和远端使用已有conda，真实模型测试仅在远端调度作业运行。逐文件同步docs中文说明，解释功能、类和核心方法；不复制权重或修改共享环境。

原生前端保持单活动作业、1×4090、4CPU、32GiB RAM、batch=1，显存22GiB停止线；每路worker各1，CPU线程各≤2。未读PCM时长、墙钟积压、送音迟到及发布延迟只记录，不再按800ms停止；PCM总量仍≤4MiB。启动空闲盘≥10GiB，每作业≤1800秒、输出≤128MiB，资源触限保留失败，不自动放慢送音、丢帧或扩大资源。

018／019历史预算封存，本次只完成030本地修订，不启动新远端模型、训练、LLM接入或现役切换。后续工作待用户另行明确指令，不自动转用历史预算。

## 4. 归档与后续研究

NTF-021／022已完成调研，相关实现从main撤回，原始结果与离线bundle保留；NTF-023—025未实施归档，NTF-026的入口修复随实验分支撤回。当前不继续最小X2教师替换或其消融，不能把外接路线选择解释为已证明教师适配不可能。详见[本次记录](reports/soulx/20261102-external-asr-plan-restore/README.md)。

普通回答生成边界、单一输出执行点及TTS播放所有权保持；状态统一经联合快照交付，撤回前端专用停止旁路。后续CoT条件化控制目标仍见[架构第2.5节](research_design/architecture.md#25-soulx-的-cot-条件化控制)，本次不构造训练数据或注入CoT。图源及PDF／PNG已由NTF-017同步；不表示回答或播放链路已实现。

历史[X2教师30条](reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)、[归因](reports/soulx/20261101-ntf012-x2-teacher-fdb30/regression_analysis.md)与[双ASR实验](../reports/soulx/20261031-dual-asr-publication/README.md)保留原分母和限制。TextTurn、VoxTurn、XTurnix继续归档，不恢复旧训练或已取消benchmark。

160ms推进合同见[设计第2.1节](dev/SoulX-Duplug/independent_streaming_frontend.md#21-每160ms音频步的推进屏障)，015／016已实现计算基础，NTF-017已完成本次联合发布迁移；原作业矩阵与资源预算不扩大。
