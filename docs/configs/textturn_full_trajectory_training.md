# 完整轨迹训练配置

`configs/textturn_full_trajectory_training.json`沿用TT-002基模、LoRA、优化器与每阶段两轮设置。`loss_policy`表示冻结数据基础权重，必须与manifest一致。2026-10-26按用户指令新增独立`loss_balance`：方法`stage_action_mass`，keep／start／stop各1/3；在pilot和full分别计算有效权重、固定平均权重为1，不修改旧冻结样本。设计公式与风险见[损失说明](../scripts/training/textturn_loss.md)。

`development_gate.minimum_success_rates`将正常接话、陈述接话、打断门槛各设1%。保留综合分高于初始化基线和误start／误stop回归容忍度0.02；开发集须完整执行、指标分母与基线相同且无未知。先按资格选模，再比较综合分，最终继续外部测试还须选中full阶段候选并重新满足全部条件；完整条件见[放行说明](../scripts/training/textturn_gate.md)。

pilot最多2000窗、full最多10000窗；所有窗口有正权重，只打乱轨迹顺序。2026-10-26用户授权取消训练时间上限，max_wall_seconds=null；显存22GiB、资产10GiB和报告2GiB限制保留，CPU8／RAM32GiB／单GPU由调度配置约束。训练内外层timeout同步移除，按有限epoch自然完成；本次授权重新启动独立run，检查点保存时机保持。TT-010仍以实际运行及质量结果验收。
