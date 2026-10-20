# 四配置适配计划

`scripts/training/prepare_layer1_adaptation.py`仅生成可审计计划，不加载模型或提交作业。无类；`build_plan`核验共享索引、三臂数据、预算、T3分配和正式参数，记录B0及三训练臂、保存点、开发集视图和来源摘要；`release_blockers`给出当前开训缺项，`validate_formal_config`由正式训练入口复用以防绕过门禁。

029切换2048时，窗口、对话数和完整单epoch步数改为从正式配置读取并与协议及完整索引交叉检查，不在校验器中固化旧512/5,763常量。B0仍不训练，三臂必须使用同一登记窗口与监督预算。

门禁包括001/004/005已通过、`training_released=true`、007合成文本dev准备完成，以及可校验的`text_dev_manifest`、`dev_selection_config`和`evaluator`。文本dev清单引用004既有审计manifest，并与`data.audited_dataset_manifest`一致；不要求新录音。缺项写入计划，`--require-release`时以非零退出；普通计划生成允许保留阻塞状态。

2026-10-20按用户澄清移除开训对真实`acceptance.sample_manifest`的检查。真实清单及其冻结属于后续迁移验收；缺失或变更不影响本阶段合成文本训练。所有输出拒绝覆盖，计划不包含可误提交的B0训练命令。
