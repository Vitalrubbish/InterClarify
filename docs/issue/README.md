# 工作单管理

更新：2026-10-23。

按用户明确指令，依据[Nemotron＋XTurnix 的 FLEURS 质量测试计划](../dev/XTurnix/quality_test_on_fleurs.md)，在 [XTurnix 工作单目录](XTurnix/README.md)推进 XTX-001—006。XTX-001 已完成输入与历史基线冻结并归档；XTX-002 已完成隔离环境、模型与协议冻结及 dev 验证并归档；XTX-003 已完成真实时钟回放器与模拟契约验证并归档；XTX-004 已完成离线评分入口与合成 trace 验证并归档；XTX-005 已完成 A10 远端作业入口与 5 条冒烟并归档；XTX-006 正式 100 条作业已按用户要求取消，随后完成 pause token 诊断，未产生正式成绩。

本次依用户明确要求，将“因果 VAD 观测辅助的 XTurnix 小规模微调”拆为 XTX-007—012，依据[训练可行性方案](../dev/XTurnix/training_feasibility.md)推进。六项均待实施；当前只创建工作单并同步计划，未构造新数据、启动训练或切换现役控制路径。新阶段与原 FLEURS 冻结试验分别记账。

| 工作单组 | 范围 | 进度 |
| --- | --- | --- |
| [XTurnix：FLEURS 两组件测试](XTurnix/README.md#fleurs-evaluation) | 固定输入与历史基线、组件协议、在线回放、独立评分、远端冒烟、100 条正式测试与报告 | 5/6 完成；XTX-006 正式作业已取消 |
| [XTurnix：VAD 辅助试训](XTurnix/README.md#vad-assisted-training) | 输入与环境、数据冻结、基线校准、训练入口及资源探针、受限试训、独立验证 | 0/6，均待实施 |

XTX-001 证据见[数据冻结报告](../../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)，XTX-002 证据见[协议冻结报告](../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)，XTX-003 证据见[回放器报告](../../reports/xturnix_fleurs/20261023-xtx-003-replay/README.md)，XTX-004 证据见[离线评分报告](../../reports/xturnix_fleurs/20261023-xtx-004-scoring/README.md)，XTX-005 证据见[A10 冒烟报告](../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)。依赖顺序及每项验收以组内入口和工作单为准。完成一项立即归档至 `docs/issue/archive/XTurnix/`，同步更新链接与状态；未实施不标记完成。真实模型测试仍需远端 conda、单作业及既定内存/磁盘上限。

此前 X2-Turn 实现和测试及其 X2Q 工作单已撤下，不因本轮工作单创建而恢复。历史记录可从 Git 与回退备份追溯。

研究范围与模块职责见[研究主文档](../research_design.md)，实施顺序与待定参数见[工程实施计划](../engineering_implementation.md)。XTX-007—012 仅覆盖四类普通控制的训练与影子验证，不包含 CoT 条件化主动介入训练、Layer 0/1/2 训练、完整播放链集成或现役替换，也不恢复此前取消的测试。
