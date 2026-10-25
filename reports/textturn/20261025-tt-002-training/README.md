# TextTurn训练交付

2026-10-25核查完成。训练run为`tt-002-20261025-r1`，作业`job-179286310634760697957-xuan-zhang`，源码`74b0846`，退出码0。完成2000快照pilot及10000快照full各两轮；仅按开发集选full第2轮，候选保存和新增token重载检查通过。

| 开发集指标 | 初始基线 | 最终候选 |
| --- | --- | --- |
| 正常接话 | 0/400 | 367/400，91.75% |
| 陈述句 | 0/200 | 172/200，86% |
| 用户打断 | 86/200 | 200/200 |
| 停顿误start | 199/200 | 0/200 |
| 附和误stop | 41/200 | 0/200 |

full最后一轮平均训练loss为0.011776，训练耗时约1小时56分。候选位于远端`~/parathink-textturn/runs/tt-002-20261025-r1/best`，adapter SHA256为`32f5493835a1b21294a3b862e38da85f7d052bbc93dbf12a81c42436e144b5d17`。数据和模型版本、包清单、逐轮loss及重载原始记录保留远端；不在Git存放重复JSON。

训练结束后评估已实际运行，并非仍在waiting_for_training；最终结果与限制见[验收核查](../20261025-tt-004-results/README.md)及[评分v2](../20261025-scoring-v2/README.md)。合成开发集达标不证明真实ASR下的全部控制能力；system backchannel尚未训练。

## 原始产物保存

本地启动期原始记录保存在`artifacts/report_archive/reports/textturn/20261025-tt-002-training/`，逐文件摘要见本地`artifacts/report_archive/archive_index.json`。服务器run及其submit_logs保持原样；原始JSON、逐例轨迹和采样日志不再入库。Git历史未重写。
