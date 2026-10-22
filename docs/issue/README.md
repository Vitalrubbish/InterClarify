# 工作单管理

更新：2026-10-22。

用户已取消 FDB 测试，现要求在历史 FLEURS 100 条上保留基本转写 WER 与末端文本延迟，只把控制测试简化为输入结束后的 complete 输出率和首次延迟。当前仅完成协议更新，尚未恢复数据、实现或执行测试。[当前协议](../dev/X2-Turn/complete_test_on_fleurs.md)。

| 当前工作单 | 内容 | 状态 |
| --- | --- | --- |
| [X2Q-009](x2q_009_complete_assets.md) | 数据恢复与远端部署 | 待实施 |
| [X2Q-010](x2q_010_complete_runner.md) | 实时回放与评分 | 待实施 |
| [X2Q-011](x2q_011_complete_run.md) | 远端正式测试与报告 | 待执行 |

简化协议 [X2Q-008](archive/x2q_008_complete_protocol.md) 已完成归档。以下为历史记录。

| 工作单 | 工作单元 | 状态 | 归档说明 |
| --- | --- | --- | --- |
| [X2Q-002](archive/x2q_002_fdb_references.md) | FDB 清单与参考 | 已取消 | 用户取消 FDB 测试 |
| [X2Q-003](archive/x2q_003_streaming_replay.md) | 部署与 FDB 回放 | 已取消 | 尚未实施 |
| [X2Q-004](archive/x2q_004_state_judger.md) | FDB 状态 Judger | 已取消 | 尚未实施 |
| [X2Q-005](archive/x2q_005_quality_metrics.md) | FDB 质量评分 | 已取消 | 尚未实施 |
| [X2Q-006](archive/x2q_006_remote_quality_run.md) | FDB 正式测试 | 已取消 | 尚未执行 |
| [X2Q-007](archive/x2q_007_fleurs_verification.md) | 历史 FLEURS 与远端现状核查 | 已完成 | 未下载数据或启动模型 |

已完成并归档：[X2Q-001：实现机制调研与评测计划](archive/x2q_001_quality_plan.md)。

历史数据依据见 [FLEURS 子集核查](../dev/X2-Turn/fleurs_subset_verification.md)。研究范围与模块职责仍以 [research_design.md](../research_design.md)、[engineering_implementation.md](../engineering_implementation.md) 为准。
