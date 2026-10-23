# 工作单管理

更新：2026-10-24。

最新进展：按用户要求，[XTX-010 Listen/start–keep 校准](XTurnix/xtx_010_control_baseline_calibration.md)已完成真实远端验证，Speak/stop 校准后置。[结果](../../reports/xturnix_training/20261023-listen-calibration/README.md)显示误抢话 10.78%→5.39%，末端召回 44.31%→28.74%，未达到预设 5% 预算；未采用新阈值上线，也未启动训练。实验不依赖 VAD 扩展或完整四类训练数据。

按用户明确指令，依据[Nemotron＋XTurnix 的 FLEURS 质量测试计划](../dev/XTurnix/quality_test_on_fleurs.md)，在 [XTurnix 工作单目录](XTurnix/README.md)推进 XTX-001—006。XTX-001 已完成输入与历史基线冻结并归档；XTX-002 已完成隔离环境、模型与协议冻结及 dev 验证并归档；XTX-003 已完成真实时钟回放器与模拟契约验证并归档；XTX-004 已完成离线评分入口与合成 trace 验证并归档；XTX-005 已完成 A10 远端作业入口与 5 条冒烟并归档；XTX-006 正式 100 条作业已按用户要求取消，随后完成 pause token 诊断，未产生正式成绩。

XTX-007 已完成[实际分析](../dev/XTurnix/training_feasibility_assessment.md)，[工作单](archive/XTurnix/xtx_007_training_feasibility.md)已归档。[XTX-009](XTurnix/xtx_009_training_data_freeze.md) 已交付[48 会话首轮审核](../dev/XTurnix/source_audit.md)，正式训练冻结仍未完成。后按用户指令单独完成 Listen 文本校准；约 200 场景双人试标、VAD 输入/环境与训练未启动，不切换现役控制路径。

| 工作单组 | 范围 | 进度 |
| --- | --- | --- |
| [XTurnix：FLEURS 两组件测试](XTurnix/README.md#fleurs-evaluation) | 固定输入与历史基线、组件协议、在线回放、独立评分、远端冒烟、100 条正式测试与报告 | 5/6 完成；XTX-006 正式作业已取消 |
| [XTurnix：可行性分析及条件性试训](XTurnix/README.md#vad-assisted-training) | 分析与讨论完成；已开展首轮来源审核，正式输入/数据及训练待条件 | 1/7；XTX-007 已归档，XTX-009 首轮审核完成、本项未完成 |

XTX-001 证据见[数据冻结报告](../../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)，XTX-002 证据见[协议冻结报告](../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)，XTX-003 证据见[回放器报告](../../reports/xturnix_fleurs/20261023-xtx-003-replay/README.md)，XTX-004 证据见[离线评分报告](../../reports/xturnix_fleurs/20261023-xtx-004-scoring/README.md)，XTX-005 证据见[A10 冒烟报告](../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)。依赖顺序及每项验收以组内入口和工作单为准。完成一项立即归档至 `docs/issue/archive/XTurnix/`，同步更新链接与状态；未实施不标记完成。真实模型测试仍需远端 conda、单作业及既定内存/磁盘上限。

此前 X2-Turn 实现和测试及其 X2Q 工作单已撤下，不因本轮工作单创建而恢复。历史记录可从 Git 与回退备份追溯。

研究范围与模块职责见[研究主文档](../research_design.md)，实施顺序与待定参数见[工程实施计划](../engineering_implementation.md)。XTX-007 完成的是分析与讨论，XTX-009 当前完成的是首轮来源审核，均不代表四类监督或训练通过。普通控制训练与影子验证继续作为条件性计划，不包含 CoT 条件化主动介入训练、Layer 0/1/2 训练、完整播放链集成或现役替换，也不恢复此前取消的测试。
