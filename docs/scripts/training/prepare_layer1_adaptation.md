# 四配置适配计划

`scripts/training/prepare_layer1_adaptation.py`仅生成可审计计划，不加载模型或提交作业。无类；`build_plan`核验共享索引、三臂数据、预算、T3分配和正式参数，记录B0及三训练臂、保存点、开发集视图和来源摘要；`release_blockers`给出当前开训缺项，`validate_formal_config`由正式训练入口复用以防绕过门禁。

门禁包括001/004/005已通过、`training_released=true`、007开训前冻结、可校验的样本清单/评价配置/评测器。缺项写入计划，`--require-release`时以非零退出；普通计划生成允许保留阻塞状态。最终真实test验收不是开训前完成条件。所有输出拒绝覆盖，计划不包含可误提交的B0训练命令。
