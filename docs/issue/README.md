# 工作单管理

更新：2026-11-07。当前前端路线为 **SoulX-Duplug 官方配置＋并行 X2Streaming-ASR**。第一阶段 ASR-Frontend 已收口；Layer 1 首轮从官方 Qwen2.5-7B-Instruct 开始协议适配，Qwen3 为后续候选，接入与训练尚未实施。

## 当前工作单

DCT-007 已完成并归档：按用户在周期输入精简讨论中的明确取舍，将 [Layer 2 输入](../dev/layer2/protocol.md#2-每周期接收什么)合并为对话与任务资料、自身上下文；助手文本不保留输出状态，纯控制／播放状态变化不唤醒任务。协议、架构、接口与数据设计已同步，链接增量检查及既有 pilot 七份摘要校验通过；运行时执行账本保留，旧 pilot 待后续适配。

DCT-006 已完成并归档：按用户目录约定，将 Layer 2 周期协议迁至 [docs/dev/layer2/protocol.md](../dev/layer2/protocol.md)，同步九份入口文档与归档记录的引用。协议正文保持，迁移链接检查通过；后续开发协议按模块归入 `docs/dev`。

DCT-005 已完成并归档：按用户明确要求交付 [Layer 2 周期协议](../dev/layer2/protocol.md)，定义输入快照、简短当前分析、三值任务进度及双下游消费。38 个本地链接／锚点及两组装箱数值校验通过；既有 pilot 摘要保持。仅交付设计与合同同步，未实施运行时、升级数据或开展训练。

DCT-002—004 已完成并归档：五个独立来源、13 条模拟轨迹及三模块 SFT 语义视图已生成；展开样本 26／48／16，去重监督 18／36／9。本地 112 项回归、远端 17 项边界测试通过，远端生成退出 0、主要产物与清单 SHA256 全部一致。音频、真实前端、独立审核及训练待后续，全部样本关闭正式训练资格。见[试造入口](../datagen/README.md)及[远端证据](../datagen/remote_validation.md)。

NTF-065已完成恢复与重提并归档：按用户明确指令复用r4已通过冒烟和源码4821efe，正式30条作业job-179401870522620182164-xuan-zhang于2026-11-07 10:31:45提交，10:32为Pending。衔接PID761589正常、单实例锁已持有，状态waiting_formal；审计成功后自动单卡评分，衔接期限至今日22:31。最多一个作业并发，完整实验仍由NTF-054验收，见[恢复证据](../reports/soulx/20261105-ntf054-retest/resume_r4_20261107.json)。

NTF-054于2026-11-07 10:15复核：r4冒烟3/3完成、退出0，492批及3份实际播放录音审计通过；三条最大控制积压低于652ms。打断104仍漏掉garden并回答股票话题，工程放行不代表内容或正式TOR通过。原衔接与timeout进程已退出，campaign的waiting_smoke已过期，正式30条和评分均未提交；当前队列为空。此次未重提作业，完整复测保持未完成，见[冒烟复核](../reports/soulx/20261105-ntf054-retest/smoke_r4_review.md)及[审计快照](../reports/soulx/20261105-ntf054-retest/smoke_r4_audit.json)。

NTF-054于2026-11-06 12:26核验：r4仍在节点绑定前Pending，尚未启动容器；提交时曾有可分配到052的调度条件，但没有实际绑定。069节点禁止调度，具体队列准入原因受查询权限限制尚不确定；衔接正常。本次仅查询，未修改任务，见[调度证据](../reports/soulx/20261105-ntf054-retest/scheduler_20261106_1226.json)。

NTF-064 已完成并归档：恢复复测输出父目录，入口自动准备父目录且拒绝覆盖已有run；源码4821efe已推送，r4 smoke作业job-179392426378993291113-xuan-zhang于08:17提交，08:19为Pending，顺序衔接正常。shell及6项衔接回归通过；完整实验仍由NTF-054验收。证据见[launch_r4.json](../reports/soulx/20261105-ntf054-retest/launch_r4.json)。

NTF-063 已完成并归档：按用户要求删除架构图模块标题下方及图旁的叙述说明，保留模块和连接关系，收紧布局并重新生成 [PDF／PNG](../figures/parathink_method_preview.md)。本地编译、导出文字及图片布局检查通过；架构行为保持现有设计。

NTF-061／062 已按用户最终确认完成并归档：保留 X-Talk 工程框架与当前 SoulX＋X2＋Qwen2.5＋IndexTTS 基线，删除 DuplexCascade 及旧组件／评测链路和七个专用测试文件；删除静态并发读取冗余用例，保留当前评分边界。本地 95 项回归通过（原 149 项），导入及本地链接检查通过。详见[清理与测试取舍](../runtime_baseline.md#清理与单元测试)。NTF-054 活动复测保持。

NTF-058／059／060 已完成旧候选路线、入口文档与早期报告证据整理并归档。删除旧候选加载器和固定 25 条重放入口；保留现役基线及 NTF-054 活动证据。conda 本地 149 项回归通过，6 份迁移证据 SHA256 一致。清理清单见[维护记录](../runtime_baseline.md)。

NTF-057已按用户指令取消完整系统原生控制一致性检查并归档；r4继续保持该范围。[NTF-054](NTF-054.md)的r3因runs父目录缺失在加载模型前失败、样本0/3；用户随后要求重提，NTF-064已完成父目录修复及r4提交。r4冒烟现已通过工程审计，NTF-065恢复原衔接并提交正式30条，评分待正式审计后提交，完整复测尚未完成。最新证据见[运行记录](../reports/soulx/20261105-ntf054-retest/README.md)及[恢复记录](../reports/soulx/20261105-ntf054-retest/resume_r4_20261107.json)，r3失败证据保留。

NTF-056已完成[NTF-054失败原因调查](../reports/soulx/20261105-ntf054-retest/failure_analysis.md)并归档：complete整段识别省略后，dither的CPU随机数消耗偏移；单卡基线完整复现3处差异，仅补齐特征提取后275条轨迹对照通过。用户随后取消本次对照，不实施RNG修复；调度查询已增加有限重试。

NTF-055已完成此前r2重提与跟踪切换并归档。原r2 smoke样本0/3及失败现场保持；当前r3正式30条和评分待smoke通过后提交。固定分母、完整预热、线程预算、样本／录音及资源审计保持，不将取消检查、诊断通过或任务提交记为正式复测完成。

NTF-052／053已完成[固定执行线程、CPU资源配置及跳过complete重识别](../dev/SoulX-Duplug/runtime_execution_update.md)并归档，完整本地146项回归通过。160ms联合提交、短窗状态识别和reset保持；尚未远端复测性能／TOR。

NTF-051 已完成[长尾机制复核与具体修复方案](../dev/SoulX-Duplug/frontend_repair_plan.md)并归档：历史 CPU fbank 剖析、执行线程差异、FunASR 线程覆盖与缓存清理，以及服务交接／正文晚到的修复和验证计划；未修改推理或启动新模型作业。

NTF-050 已完成[最新 FDB30 控制积压与 TOR 归因](../reports/soulx/20261105-fdb30-half-duplex/control_backlog_analysis.md)并归档：逐批定位控制路长尾、服务层等待兜底消费差异，并按相同 ID 复核历史纯 SoulX 成绩；未修改推理或启动 GPU 作业。

NTF-049 已完成[训练数据构造、配比与分阶段时长方案](../dev/layer1_training/README.md)并归档：提出七类数据、10 万条决策样本及四阶段训练预算，吞吐待远端校准。当前[训练设计](../research_design/layer1_training.md)首轮采用 Qwen2.5-7B-Instruct，Qwen3 保留为后续候选；依次训练协议、含噪状态与取消恢复、附和及 thinking。此前 NTF-037、040—048 的分析与设计单均已归档，未启动语料生成、下游接入或训练。NTF-039 已完成前端文档与接口收口；NTF-038 的 [SoulX 原生 complete 行为审计](../reports/soulx/20261104-completion-strategy-audit/README.md)与 NTF-019 前端验收保持。

## 当前路线交付

| 工作单 | 状态 | 交付 |
| --- | --- | --- |
| [DCT-007](../dev/layer2/protocol.md#2-每周期接收什么) | 输入精简设计完成并归档 | 两类输入、助手文本无输出状态、仅内容更新唤醒等待任务；未实施运行时或升级数据 |
| [DCT-005](../dev/layer2/protocol.md) | 周期与发布设计完成并归档 | 分析与三值任务进度、同源双下游条件、晚到／失败与监督边界；输入由 DCT-007 精简，未实施运行时 |
| NTF-065 | r4正式复测恢复与提交已完成并归档 | 复用已通过冒烟，正式30条已提交、顺序衔接正常；完整结果仍由NTF-054验收 |
| NTF-064 | 启动修复及r4重提已完成并归档 | 自动准备输出父目录且拒绝覆盖run；smoke已提交、顺序衔接正常；完整实验仍由NTF-054跟踪 |
| NTF-063 | 图示精简已完成并归档 | 删除各框标题下方及图旁说明，收紧布局，同步 PDF／PNG 与文档；本地编译和预览检查通过 |
| [NTF-057](../reports/soulx/20261105-ntf054-retest/launch_r3.json) | 取消对照及重提已完成并归档 | 完整系统显式不运行原生一致性对照，153项回归通过；r3已提交，有限重试衔接进程已启动，完整复测仍由NTF-054跟踪 |
| [NTF-056](../reports/soulx/20261105-ntf054-retest/failure_analysis.md) | 调查已完成并归档 | 真实权重完整复现及CPU特征提取干预，确认dither随机状态偏移；区分调度衔接故障，生产修复及正式复测待NTF-054 |
| [NTF-052／053](../dev/SoulX-Duplug/runtime_execution_update.md) | 实现及本地验证已完成并归档 | 固定SoulX／X2线程、各进程2线程预算、跳过complete整段识别及限定差异的控制对照；146项本地回归通过，GPU复测待后续 |
| [NTF-051](../dev/SoulX-Duplug/frontend_repair_plan.md) | 分析与方案已完成并归档 | 按证据强度拆分长尾候选，明确文件／方法和验证矩阵；后续052／053已实施本轮授权子项，其余候选待实施 |
| [NTF-050](../reports/soulx/20261105-fdb30-half-duplex/control_backlog_analysis.md) | 分析已完成并归档 | 4720 批计时、相同 ID 历史对照及 5 条接话失败归因；底层长尾机制待进一步计时 |
| [NTF-015／016](../reports/soulx/20261102-native-independent-frontend/README.md) | 已完成并归档 | 原生控制封装、冻结加载器、同源 PCM、160ms 屏障和独立 X2 适配 |
| [NTF-017](../reports/soulx/20261102-ntf017-joint-publication/README.md) | 已完成并归档 | 文本／状态／进度联合提交，移除前端停止旁路 |
| [NTF-018](../reports/soulx/20261103-ntf018-warmup/README.md) | 已完成并归档 | 完整预热、真实权重对照和并发三轴 3/3 |
| [NTF-019](../reports/soulx/20261103-ntf019-fdb30/README.md) | 已完成并归档 | 固定 FDB30 验收，用户审核通过 |
| [NTF-026](archive/NTF-026.md) | 已完成并归档 | 采集监控的进程退出竞态修复 |
| [NTF-027](archive/NTF-027.md) | 已完成并归档 | 恢复原生控制与外接 X2 工作单 |
| [NTF-028](archive/NTF-028.md) | 已完成并归档 | 160ms 音频步推进屏障合同 |
| [NTF-029](archive/NTF-029.md) | 已完成并归档 | 160ms 双路完成后的联合发布合同 |
| [NTF-030](../reports/soulx/20261103-latency-limit-removal/README.md) | 已完成并归档 | 取消 800ms 时长停止条件，保留容量与资源保护 |
| [NTF-037](../research_design/layer1_training.md) | 研究已完成并归档 | Layer 0 并入 Layer 1 的职责同步、含噪控制与取消恢复数据、规模预算及控制方案比较；尚未实施训练 |
| [NTF-038](../reports/soulx/20261104-completion-strategy-audit/README.md) | 审计已完成并归档 | 区分当前原始预测与官方规则来源；复核 3180 批次，未改推理或追加 GPU 实验 |
| NTF-039 | 已完成并归档 | 当前前端文档、快照接口与图稿一致；135 项本地检查通过 |
| [NTF-040](../dev/SoulX-Duplug/completion_runtime_analysis.md) | 分析已完成并归档 | 真实案例、官方取消与上下文整理、七组 CPU 行为核查及当前设计影响；未接入运行时 |
| [NTF-041](../dev/SoulX-Duplug/completion_runtime_analysis.md#2-提前-complete-的具体例子) | 复核已完成并归档 | 两组无新增文字状态序列、首音前取消与上下文合并实例；明确规则前字段缺失 |
| NTF-042 | 已完成并归档 | 第二节采用 TurnControlComparison 实际日志案例，时间线与引用同步 |
| NTF-043 | 已完成并归档 | 区分自写与官方运行时，澄清官方消息整理、请求重建和 KV 边界 |
| [NTF-044](../research_design/layer1_training.md) | 文档已完成并归档 | 明确运行时基线与 7B 微调关系、窗口建议、取消恢复和 8×4090 预算；未实施接入或训练 |
| [NTF-045](../research_design/layer1_training.md) | 文档已完成并归档 | 取消两条路线；其中未微调基线的能力假设已由 NTF-046 修正，未实施接入或训练 |
| [NTF-046](../research_design/layer1_training.md) | 文档已完成并归档 | 修正既有协议与新 token 适配的能力假设；新增词表须覆盖相关参数训练，路线范围以后续 NTF-047 为准 |
| [NTF-047](../research_design/layer1_training.md) | 文档已完成并归档 | 删除路线 A，仅保留协议适配后的 7B Layer 1 训练主线及其内部检查点比较与消融 |
| [NTF-048](../research_design/layer1_training.md) | 文档已完成并归档 | 将训练起点改为 Qwen2.5-7B-Instruct 或选定 Qwen3，取消旧 checkpoint／adapter 依赖，更新模式与资源预检要求 |
| [NTF-049](../dev/layer1_training/README.md) | 文档已完成并归档 | 训练数据构造、七类占比、四阶段样本分配与 8×4090 假设下的时长；未生成语料或启动训练 |

## 后续计划

NTF-031—035 为后续 LLM／Layer 1／输出运行时计划，尚未实施并归档；用户明确暂不推进接入，不记为完成成果。相关内容见本地 `docs/issue/archive/`。

## 管理约定

工作单仅按用户明确指令建立；交付满足验收后立即归档并同步索引。真实模型训练和集群测试使用远端 conda 调度作业，资源限制按相应工作单与已确认修订执行；实现同步维护 `docs` 下同路径中文说明。

`docs/issue/archive/` 不纳入 Git，保留当前路线已完成工作单。
