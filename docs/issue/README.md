# 工作单管理

更新：2026-10-23。

按用户明确指令，依据[Nemotron＋XTurnix 的 FLEURS 质量测试计划](../dev/XTurnix/quality_test_on_fleurs.md)，在 [XTurnix 工作单目录](XTurnix/README.md)新增 XTX-001—006，均为待实施。本次仅创建工作单，不启动实现、数据恢复、部署或远端测试。

| 工作单组 | 范围 | 进度 |
| --- | --- | --- |
| [XTurnix](XTurnix/README.md) | 固定输入与历史基线、组件协议、在线回放、独立评分、远端冒烟、100 条正式测试与报告 | 0/6 完成 |

依赖顺序及每项验收以组内入口和工作单为准。完成一项立即归档至 `docs/issue/archive/XTurnix/`，同步更新链接与状态；未实施不标记完成。真实模型测试仍需远端 conda、单作业及既定内存/磁盘上限。

此前 X2-Turn 实现和测试及其 X2Q 工作单已撤下，不因本轮工作单创建而恢复。历史记录可从 Git 与回退备份追溯。

研究范围与模块职责见[研究主文档](../research_design.md)，实施顺序与待定参数见[工程实施计划](../engineering_implementation.md)。本轮仅覆盖两组件测试，不创建后续训练或完整话轮集成的工作单。
