# 工程实施计划

更新：2026-10-31。本文按已确认的SoulX-Duplug路线维护实施顺序；研究范围和模块合同分别见[研究方案](research_design.md)与[架构设计](research_design/architecture.md)。已复用TurnControlComparison资产完成组件加载及独立前端Context实现，六视图实时写入检查见[报告](../reports/soulx/20261029-shared-context/README.md)。下游状态token编码、LLM与真实输出尚未接入，现役Agent未切换，不启动训练或历史benchmark。

2026-10-30 用户确认将在线接口简化为每个 160ms 音频处理步骤联合覆盖 text 与状态，不保留历史正文版本，取消 320ms 周期建议。当前值接口及前端已改造，本地契约检查及远端六视图写入检查通过；见[测试报告](../reports/soulx/20261030-current-context-test/README.md)，拼合gap与识别／状态质量限制保留。

## 1. 运行底座与目标

2026-10-30 最新用户授权覆盖下述历史首版选型：实施 [Nemotron Teacher Forcing 同步前端](dev/SoulX-Duplug/nemotron_teacher_forcing.md)，替代该实验路径的 SenseVoice 门控与滑窗识别，并运行 FDB 三轴各10条固定小样本。两份模型权重固定，不接下游、不训练；具体资源与验收见 [NTF 工作单](issue/README.md)。

2026-10-31最新设计改为[双ASR缓存发布](dev/SoulX-Duplug/dual_asr_publication.md)，工作单[NTF-005](issue/NTF-005.md)待实施：SenseVoice恢复官方控制路径，SoulX每160ms独立预测状态并暂存；Nemotron独立完成对应音频范围解码，单写者配对发布其正文和缓存状态。两路计算不等待对方发布，SharedContext仍只保留当前值。以下教师文字路径作为已实现对照，不代表新组合已经切换或验收。

现役底座仍为 X-Talk `ca9b23c`、DuplexCascade、Nemotron EN160 与 Kokoro，参数见[运行配置](runtime_baseline.md)。目标为 **Nemotron Teacher Forcing＋SoulX-Duplug 语音前端**，位于 Layer 0–Layer 2 输入侧；每步先取得Nemotron文字，经SoulX音频门控后按需消费规范化教师文字，再输入EOS预测状态，发布后解除解码屏障。同一活动话轮只使用一个权威转写来源。SenseVoice 首版及旧 Nemotron 独立组合保留为历史基线。

| 模块 | 实施职责 |
| --- | --- |
| 语音前端 | 收入 Nemotron 原生流式 ASR、逐步教师文字、SoulX 音频编码及五状态预测；向 Context 联合发布转写与状态，与下游并发执行 |
| Shared Context | 保存每个话轮最新全文与当前状态，整组原子覆盖和读取；不保留历史正文版本，不等待完成判断，后续向前端反馈已发布 CoT |
| Layer 1 | 在正常输入边界读取状态与转写，在当前 turn 看到对应 `user_complete` 后开始普通正式回答；负责思考请求与表达 |
| 输出运行时 | 统一管理 FIFO、TTS 与播放器；活动输出期间的有效 `user_nonidle` 额外直接触发停止，准备阶段也可取消 |
| Layer 2（后续） | 只发布内部 CoT，供 SoulX 与 Layer 1 使用，不生成话轮建议或待播正文 |
| Layer 0（后续） | 只预测系统附和时机，正文由表达路径提供，经同一输出运行时发声 |

其他用户状态不进入输出运行时，不映射为 start 或 keep；完成状态不新建独立 LLM 回答调用。系统保持唯一仲裁执行点与单一 TTS 播放所有权，已听内容不可撤销。状态、生成、提交、取消与实际播放分别记录，具体打断及恢复规则见[架构第 2 节](research_design/architecture.md#2-模块与动作边界)。

## 2. 前端适配顺序

1. **冻结首版资产**：已复用 SoulX、SenseVoiceSmall 及 conda，英文 `language=en`；远端单卡最小加载检查通过，版本与资源记录见[报告](../reports/soulx/20261029-frontend-deployment/README.md)。未升级现役 ASR/TTS 环境，后续接口验证仍须独立核算资源。
2. **接通语音前端**：当前已实现[教师文字前端](scripts/runtime/nemotron_teacher_frontend.md)和[同步解码进程](scripts/remote/nemotron_teacher_worker.md)，固定权重；NTF-004按官方格式规范化控制文字并恢复文字门控，原始累计正文始终发布，软重置保留语义KV。已消费token修订从独立检查点或有界账本重算，普通门控预测不写KV。此前 SenseVoice 滑窗、差分与缓存修订仅作历史对照。
3. **交付 Context 接口**：按稳定 `turn_id` 持续写入转写，不等待 `user_complete`；验证窗口重叠、修订和控制器重置不会造成漏字、重复文本或新建话轮。提供最新全文与状态的原子读取，核查修订覆盖、reset 连续、关闭及 EOF 分离，见[接口合同](dev/SoulX-Duplug/shared_context_interface.md)。
4. **打通表达与打断**：明确状态输入编码、Layer 1 生成边界和直接打断接口，验证输出标识失效、停播确认及新输出恢复；旧 DuplexCascade 控制不能与新路径重复执行。
5. **接入思考并验证重叠**：在研究模块细节确认后，验证用户未说完时转写已可读、Layer 1 可请求思考、Layer 2 可回写结果，前端与表达／思考能够重叠执行。前端 CoT 条件化仍属于后续适配与训练，不是首版链路的先决条件。
6. **小样本质量验证**：按最新授权复用 FDB 三轴各10条冻结样本，真实时钟、单卡、单作业运行，联合核查文字质量和状态时机；最新NTF-004官方格式与门控对照已交付，正式25/30积压触限、未见整体改善，见[报告](../reports/soulx/20261031-nemotron-teacher-gate/README.md)。先前独立门控组合已撤下，其历史结果不等于当前教师文字实验结果。

Nemotron独立适配的四视图单卡实时探针已完成，正文及消费版本结构一致，未增加固定稳定等待；结果和状态质量／EOF尾部限制见[组合报告](../reports/soulx/20261030-nemotron-integration/README.md)。这不代表第4／5步的下游生成、CoT或真实播放已实施。

窗口调用下的在线转写不等于原生流式ASR，160ms也不是组合延迟承诺。第1步已完成；第2／3步已提供独立实现，并用实际只读消费者验证，剩余正文缺口、低音量识别及未覆盖状态保留。第4步之后的下游接入尚未实施。此前[Easy Turn英文集方案](dev/SoulX-Duplug/quality_test.md)保留为Nemotron历史设计，不能直接套用首版；本轮结果不扩大为完整表达、思考或实际播放验收。后续替换ASR时独立冻结来源、修订及Context映射，不在活动话轮中热切换。

## 3. 后续研究模块

SoulX 联合音频 token、转写文本 token 与已发布 CoT token 的目标已确认，当前不实现。序列、边界编码、缓存、触发方式、输出是否扩展及训练配置按[架构第 2.5 节](research_design/architecture.md#25-soulx-的-cot-条件化控制)后续确定，不继承旧文本控制器协议。

Layer 1 表达与思考调用、Layer 2 分步分析及两组专项训练采用[共同训练约定](research_design/architecture.md#7-共同训练与数据约定)。Layer 0 系统附和专项保留在总计划，具体模型、数据规模和预算实施前细化，当前不采集或训练。Layer 3 定位待统一，不新增实现。

完整话轮评测另行规划，可参考 FDB 的接话、停顿、用户附和及打断子集；系统附和须独立核查合理性与实际发声。控制返回时间不能代替可听响应时间，历史 FDB/FLEURS 作业不自动恢复。

## 4. 环境、资源与交付

本地与远端均使用 conda，真实模型训练和集群测试在远端调度作业执行。SoulX 实验使用独立根目录 `~/parathink-soulx-duplug/`，现役模型与环境只读复用，目录见[远端约定](remote_workspace.md)。

此前公开集验证设计的上限为：1×24GiB GPU、8 CPU、32GiB RAM、batch=1、一个活动作业，显存停止线 22GiB；下载并发≤2、CPU worker≤2，单会话一个在途请求、待处理音频≤800ms。单作业≤4小时，冒烟与正式运行累计≤4 GPU小时；启动空盘≥30GiB，新增资产≤10GiB，其中报告／trace≤2GiB。执行前核算全量时长和峰值，触限停止，不自动扩容。这些限制不覆盖已归档 TextTurn 训练的历史授权，也不恢复其作业。

实施代码、配置及必要契约测试同步维护 `docs` 下同路径中文说明；交付冻结配置、manifest、逐例 trace、汇总、资源记录与中文报告。工作单仅依用户明确指令建立，完成后归档；本次教师文字接入和三轴小样本已按指令建立 NTF-001／002。

## 5. 历史路线入口

TextTurn、VoxTurn、XTurnix 已全部归档，不再有活动工作单；路线说明、实现和证据分别保留在[归档区](archive/dev/README.md)、[archive/](../archive/README.md)和[报告](../reports/README.md)。旧协议不作为 SoulX 已实现能力或当前实施授权。

| 路线 | 归档状态与证据 |
| --- | --- |
| [TextTurn](archive/dev/TextTurn/README.md) | 数据、训练、接入及评测已归档；TT-010 有限 pilot 最后记录见[修复报告](../reports/textturn/20261027-dataset-repair/README.md)，不恢复 full 或 TT-011 |
| [VoxTurn](archive/dev/VoxTurn/research_assessment.md) | 仅完成现成权重与接入可行性调研，未部署、未训练 |
| [XTurnix](archive/dev/XTurnix/README.md) | XTX-001—005 及可行性分析已归档；正式 FLEURS 作业已取消，来源审核未形成可冻结监督 |

历史工作单在本地 `docs/issue/archive/`，不进入 Git；历史协议及运行证据保留在对应归档文档和报告，不作为 SoulX 已实现能力或当前实施授权。
