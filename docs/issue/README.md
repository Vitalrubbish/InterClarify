# 工作单管理

更新：2026-10-22。

历史工作单已按此前要求清理，不重建。依据本次明确的 X2-Turn 独立 FDB 质量测试请求，仅为本轮计划新增以下工作单；当前只完成调研与计划，尚未开始部署或实现。

| 工作单 | 工作单元 | 状态 | 依赖 |
| --- | --- | --- | --- |
| [X2Q-002](x2q_002_fdb_references.md) | FDB 清单、核验转写与用户末端边界 | 待实施 | 无 |
| [X2Q-003](x2q_003_streaming_replay.md) | 远端部署、流式协议与实时回放 | 待实施 | X2Q-002 的输入清单 |
| [X2Q-004](x2q_004_state_judger.md) | 独立状态 Judger 与参考时间投影 | 待实施 | X2Q-002、X2Q-003 的帧映射 |
| [X2Q-005](x2q_005_quality_metrics.md) | WER、末端延迟与状态匹配评分 | 待实施 | X2Q-002—004 的数据合同 |
| [X2Q-006](x2q_006_remote_quality_run.md) | 远端冒烟、正式回放与质量报告 | 待实施 | X2Q-002—005 |

已完成并归档：[X2Q-001：实现机制调研与评测计划](archive/x2q_001_quality_plan.md)。

详细协议见 [X2-Turn FDB 质量测试计划](../dev/X2-Turn/qualtity_test_on_fdb.md)。研究范围与模块职责仍以 [research_design.md](../research_design.md)、[engineering_implementation.md](../engineering_implementation.md) 为准。本次交付为计划，后续实现按工作单顺序推进。
