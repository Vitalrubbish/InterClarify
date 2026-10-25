# 工作单管理

2026-10-25最新纠正：用户明确FDB只监控TextTurn，不需要模拟回答。TT-005／006及TT-007统一移除助手正文和生成／播放生命周期，状态仅由start／stop／keep驱动；旧480ms r3停止并保留撤回记录，修正后的480ms与160ms复用相同100条录音、候选和原累计预算，串行重提。修正后的480ms r4已运行，160ms续接器等待其结束后自动提交；详见[动作监控运行记录](../../reports/textturn/20261025-fdb-action-only/README.md)。

2026-10-25新增授权：用户要求新增[TT-007：160ms周期同样本FDB对照](TextTurn/tt_007_fdb_160ms.md)，复用TT-005／006的100条录音、现有候选和原累计预算，原480ms作业继续运行。先更新研究范围中的周期实验例外，再实现参数化控制与评分；160ms测试串行排在480ms作业之后，当前尚未提交160msGPU作业。

2026-10-25 最新工作单：按用户要求修复 [TextTurn TT-004](TextTurn/tt_004_evaluation.md)评分器，再审计训练数据。当前TT-001—003共3项已归档；v2评分已在远端conda对原1200例trace及19994个文本窗口离线重评，不占GPU、不改候选。v2分离错误与未知，移除完整参考自动语义锚点；打断299/1、停顿298/2、附和173/127为正确/未知，接话600未知，整体证据不足，TT-004待语义标注覆盖后归档。数据审核发现时序捷径、固定模板和重复keep占比过高，给出构造及候选配比建议；冻结数据和训练未改动，不新建issue。详见[v2修复及数据审核](../../reports/textturn/20261025-scoring-v2/README.md)。

2026-10-25启动更新：用户已明确授权启动TT-005／006，已实现共用冻结、回放、评分和远端提交入口，本地6项边界测试通过；335候选中固定50＋50，Pause共62个标注区间。当前处于远端执行阶段，原始失败和修复记录保留，不提前归档、不宣称质量通过。详见[联合运行记录](../../reports/textturn/20261025-fdb-cross-dataset/README.md)。

2026-10-25最新补充：按用户明确要求，依据[两臂跨数据集计划](../dev/TextTurn/fdb_cross_dataset_plan.md)建立[TT-005：接话覆盖与延迟](TextTurn/tt_005_fdb_turn_taking.md)及[TT-006：停顿介入率与归因](TextTurn/tt_006_fdb_pause_handling.md)，分别交付50条真实录音结果，替代此前仅纳入TT-004的安排。必要抽样、适配和边界测试并入两项，不单设工程确认工作单；共用一次远端串行测试与原有预算。当前只有计划及工作单，没有冻结抽样、实现入口或提交作业。固定现有候选、真实ASR、Listen影子动作，FDB标注时序与当前语义策略分开报告；TT-004仍未完成，旧完整FDB作业不恢复。

2026-10-24 当前路线：用户已确认 **SoulX-Duplug＋Nemotron**，并要求简化为公开英文 Easy Turn 集上的质量与延迟测试；[方案](../dev/SoulX-Duplug/quality_test.md)已同步。本次只更新路线文档，未新建 issue、实现适配或启动远端作业。以下 XTurnix 内容保留为历史记录，不代表当前继续推进旧训练或恢复已取消测试。

2026-10-24 回滚说明：用户明确选择撤销全部阈值实验，恢复 `13ba980` 的工作单与实现记录；其后校准、ASR 时间控制、短延迟和训练入口草案已清理。以下为基点保留状态，不代表重新授权旧训练或取消的测试。当前仅执行[回滚清理](../dev/XTurnix/rollback_cleanup.md)，没有新建工作单。

更新：2026-10-23。

按用户明确指令，依据[Nemotron＋XTurnix 的 FLEURS 质量测试计划](../dev/XTurnix/quality_test_on_fleurs.md)，在 [XTurnix 工作单目录](XTurnix/README.md)推进 XTX-001—006。XTX-001 已完成输入与历史基线冻结并归档；XTX-002 已完成隔离环境、模型与协议冻结及 dev 验证并归档；XTX-003 已完成真实时钟回放器与模拟契约验证并归档；XTX-004 已完成离线评分入口与合成 trace 验证并归档；XTX-005 已完成 A10 远端作业入口与 5 条冒烟并归档；XTX-006 正式 100 条作业已按用户要求取消，随后完成 pause token 诊断，未产生正式成绩。

XTX-007 已完成[实际分析](../dev/XTurnix/training_feasibility_assessment.md)，用户同意先启动 40—60 个英文场景的来源与可判定性审核，[分析工作单](archive/XTurnix/xtx_007_training_feasibility.md)已归档。[XTX-009](XTurnix/xtx_009_training_data_freeze.md) 已交付[48 会话首轮审核](../dev/XTurnix/source_audit.md)：30 个条件候选、18 个歧义，当前可直接冻结的训练记录为 0。本次只放行来源审核，正式冻结仍依赖 XTX-008，约 200 场景双人试标、输入/环境、校准及训练均未启动；不切换现役控制路径。

| 工作单组 | 范围 | 进度 |
| --- | --- | --- |
| [XTurnix：FLEURS 两组件测试](XTurnix/README.md#fleurs-evaluation) | 固定输入与历史基线、组件协议、在线回放、独立评分、远端冒烟、100 条正式测试与报告 | 5/6 完成；XTX-006 正式作业已取消 |
| [XTurnix：可行性分析及条件性试训](XTurnix/README.md#vad-assisted-training) | 分析与讨论完成；已开展首轮来源审核，正式输入/数据及训练待条件 | 1/7；XTX-007 已归档，XTX-009 首轮审核完成、本项未完成 |

XTX-001 证据见[数据冻结报告](../../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)，XTX-002 证据见[协议冻结报告](../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)，XTX-003 证据见[回放器报告](../../reports/xturnix_fleurs/20261023-xtx-003-replay/README.md)，XTX-004 证据见[离线评分报告](../../reports/xturnix_fleurs/20261023-xtx-004-scoring/README.md)，XTX-005 证据见[A10 冒烟报告](../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)。依赖顺序及每项验收以组内入口和工作单为准。完成一项立即归档至 `docs/issue/archive/XTurnix/`，同步更新链接与状态；未实施不标记完成。真实模型测试仍需远端 conda、单作业及既定内存/磁盘上限。

此前 X2-Turn 实现和测试及其 X2Q 工作单已撤下，不因本轮工作单创建而恢复。历史记录可从 Git 与回退备份追溯。

研究范围与模块职责见[研究主文档](../research_design.md)，实施顺序与待定参数见[工程实施计划](../engineering_implementation.md)。XTX-007 完成的是分析与讨论，XTX-009 当前完成的是首轮来源审核，均不代表四类监督或训练通过。普通控制训练与影子验证继续作为条件性计划，不包含 CoT 条件化主动介入训练、Layer 0/1/2 训练、完整播放链集成或现役替换，也不恢复此前取消的测试。
