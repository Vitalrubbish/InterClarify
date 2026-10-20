# Issue 046：精简 reports/layer1_training

状态：完成，归档。优先级：P2。日期：2026-10-20。依据：用户要求该目录只保留极其必要的内容。

## 保留原则

只保留两类文件：

1. 当前代码、配置或测试直接读取的输入或索引。
2. 正式阶段报告 `docs/layer1_training_fdb_report.md`、训练对照与协议文档直接引用的最终证据。

## 删除范围

- 整目录删除：`issue006-preparation-20261020`、`issue017-loading-20261019`、`issue028-gate-scope-20261020`、`issue033-fdb-20261020`。
- 其余目录删除过程日志、启动快照、环境清单、重复 JSON/CSV、损失曲线及已归档中间产物；保留 README 中的结论与必要链接。
- `issue037` 仅保留 `results.md`；`issue034` 仅保留 `analysis/analysis.json`；`issue006-round1` 仅保留 `completion.json`；`issue016` 仅保留 `source_verification.json`。

## 保留清单

- `issue001-inventory`：资产与来源清单（配置直接引用）。
- `issue001-word`：README、Word清单、比较摘要及摘要校验文件（协议直接引用）。
- `issue004-build-r5`：README、机器审计、数据集 manifest 及 README 引用的小型产物。
- `issue006-round1`：`completion.json`（训练对照引用）。
- `issue016`：`source_verification.json`（协议说明引用）。
- `issue026`：README（协议 `resource_report`）。
- `issue029`：README 与完整索引（配置/测试直接引用）。
- `issue030`：README 与 FDB 清单（作业脚本直接引用）。
- `issue034`：`analysis/analysis.json`（阶段报告引用）。
- `issue035`：README、`evidence.json`、`public_sources.json`（训练对照引用）。
- `issue037`：`results.md`（阶段报告引用）。
- `issue040` 数据、训练、FDB 与 token 审计：README、审计、完整索引、训练 summary/候选重载、最终 FDB 结果/CSV/关闭记录等直接证据。

## 验证

- `tests.test_layer1_adaptation`、`tests.test_layer1_delayed_training`、`tests.test_layer1_alignment` 共 26 项通过（`ml-hw1`）。
- 当前跟踪文档与保留报告相对链接扫描无悬空项。
- `reports/layer1_training` 由约 9.6MiB 降至约 1.5MiB，保留 55 个文件。
