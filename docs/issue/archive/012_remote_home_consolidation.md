# Issue 012：归拢远端主目录的历史实验目录

状态：完成，2026-10-19。范围：响应用户主目录过多的反馈，减少InterClarify历史目录，不处理其他项目。

- [x] 核对现行脚本、软链接、conda prefix和任务，保护模型/数据源、v1实际组件环境、v6现行入口、训练目录和仓库。
- [x] 24个历史目录移到 `interclarify-archive/runs/` 及 `maintenance/`，3份顶层传输包归到 `transfers/`，旧位置不建同名链接。
- [x] 同文件系统串行rename，全部目录inode不变；git工作树修复后可用，原有效软链接仍有效。
- [x] 删除已确认空目录ic_bctest；未确认冗余的原始数据不删，不再复制或压缩大型结果。
- [x] 顶层可见目录50→26，现役客户端导入通过，组件和训练prefix存在；精确迁移/保留清单及验证齐全。

[执行报告](../../../reports/maintenance/20261019-home-consolidation/README.md)、[目录约定](../../remote_workspace.md)。归拢不等于释放历史数据空间，本轮不新增集群作业、不改变训练门禁。011恢复原件已移到 `interclarify-archive/maintenance/retired-selection-20261019/`；历史报告路径仍按原值保留，恢复时查询012映射。任务完成归档。
