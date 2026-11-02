# 工程实施计划

更新：2026-11-02。当前路线为**原生SoulX＋SenseVoice控制、独立X2完整词正文、仅complete交接同步**。NTF-015／016已完成本地实现与契约验收并归档，见[交付记录](reports/soulx/20261102-native-independent-frontend/README.md)；NTF-017／020／018／019仍待实施。本次没有提交远端模型作业，路线恢复历史见[恢复记录](reports/soulx/20261102-external-asr-plan-restore/README.md)。

## 1. 当前目标与运行底座

SoulX保留内部SenseVoice教师、门控、滑窗差分／KV修订、状态规则、反馈和原生reset；X2只为共享上下文提供独立正文，不将外接转写注入状态KV。两路读取同一持续PCM。每160ms批次等X2完成两个80ms原生步及其组内解码、SoulX完成本步原生调用后，将EOS闭合正文和状态token一次写入SharedContext；提交成功后才允许下一步。先完成结果只在内部暂存，不写原始PCM。

五状态统一经过本批次联合提交，不设置前端nonidle专用停止钩子。complete原始预测先在内部记录，只有X2真实解码进度覆盖固定目标、开放组真实闭合且正文已提交，才交接ready供Layer 1当前turn使用；ready不保证尾词必齐。详细合同见[独立前端](dev/SoulX-Duplug/independent_streaming_frontend.md)及[Context接口](dev/SoulX-Duplug/shared_context_interface.md)。

现役底座仍见[运行配置](runtime_baseline.md)，本次不切换Agent。官方源码使用[固定子模块及远端checkout](third_party/soulx-duplug.md)，不恢复已退役comparison加载器。历史教师替换和双ASR实验只作证据，不代替新封装的输入／reset等价性验证。

## 2. 工作顺序与交付

| 顺序 | 工作单 | 交付与进入下一步的条件 |
| --- | --- | --- |
| 1 | [NTF-015](reports/soulx/20261102-native-independent-frontend/README.md) | 已完成：原生协议控制封装、冻结加载器、状态来源与reset审计 |
| 2 | [NTF-016](reports/soulx/20261102-native-independent-frontend/README.md) | 已完成：同源PCM、X2原生80ms适配、160ms屏障、EOS正文／真实进度回调 |
| 3 | [NTF-017](issue/NTF-017.md) | 160ms两路完成后文本／状态／进度联合写入、移除前端停止旁路、短锁生命周期；同步图源 |
| 4 | [NTF-020](issue/NTF-020.md) | 仅complete的进度追齐、取消、去重和有界超时 |
| 5 | [NTF-018](issue/NTF-018.md) | 同一拓扑完整预热、有限预热对照和单路参考；预检3/3完整、退出0且无800ms过载 |
| 6 | [NTF-019](issue/NTF-019.md) | 原固定FDB30单／双路验收，分别评价原始状态、正文、实际交接与尾部 |

015／016本地验收已完成，尚未进行真实权重等价性／实时性验收。下一步为017原子Context及020交接，018通过后才启动019。NTF-017需将015／016既有回调迁移到当前批次暂存，再联合写入Context，移除前端专用停止接入；原历史验收不能代替新合同检查。内部reset不清正文，交接pending不阻止联合提交成功后的下一批推进，生产者持续收音。

## 3. 资源与执行边界

本地和远端使用已有conda，真实模型测试仅在远端调度作业运行。逐文件同步docs中文说明，解释功能、类和核心方法；不复制权重或修改共享环境。

单活动作业、1×4090、4CPU、32GiB RAM、batch=1，显存22GiB停止线；每路worker各1，CPU线程各≤2。每路未读PCM、送音迟到及发布延迟沿用800ms停止线，PCM总量≤4MiB；启动空闲盘≥10GiB，每作业≤1800秒、输出≤128MiB。触限保留失败，不自动放慢送音、丢帧、筛选重跑或扩大资源。

恢复NTF-018最多2个串行作业、NTF-019最多2个串行作业的计划上限，合计≤2 GPU小时／512MiB；实施前冻结具体矩阵、输入、预热覆盖和时钟，不借用NTF-021—026的历史额度。本次恢复工作单不启动这些作业，不训练、不接真实LLM／CoT／TTS、不切换下游。

## 4. 归档与后续研究

NTF-021／022已完成调研，相关实现从main撤回，原始结果与离线bundle保留；NTF-023—025未实施归档，NTF-026的入口修复随实验分支撤回。当前不继续最小X2教师替换或其消融，不能把外接路线选择解释为已证明教师适配不可能。详见[本次记录](reports/soulx/20261102-external-asr-plan-restore/README.md)。

普通回答生成边界、单一输出执行点及TTS播放所有权保持；状态统一经联合快照交付，撤回前端专用停止旁路。后续CoT条件化控制目标仍见[架构第2.5节](research_design/architecture.md#25-soulx-的-cot-条件化控制)，本次不构造训练数据或注入CoT。图源改造由恢复后的NTF-017执行，本次不修改图文件。

历史[X2教师30条](reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)、[归因](reports/soulx/20261101-ntf012-x2-teacher-fdb30/regression_analysis.md)与[双ASR实验](../reports/soulx/20261031-dual-asr-publication/README.md)保留原分母和限制。TextTurn、VoxTurn、XTurnix继续归档，不恢复旧训练或已取消benchmark。

160ms推进合同见[设计第2.1节](dev/SoulX-Duplug/independent_streaming_frontend.md#21-每160ms音频步的推进屏障)，015／016已实现计算基础，NTF-017负责本次联合发布迁移；原作业矩阵与资源预算不扩大。
