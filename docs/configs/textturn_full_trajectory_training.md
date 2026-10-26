# 完整轨迹训练配置

`configs/textturn_full_trajectory_training.json`沿用TT-002基模、LoRA、优化器与每阶段两轮设置。`loss_policy`表示冻结数据基础权重，必须与manifest一致。2026-10-26按用户指令新增独立`loss_balance`：方法`stage_action_mass`，keep／start／stop各1/3；在pilot和full分别计算有效权重、固定平均权重为1，不修改旧冻结样本。设计公式与风险见[损失说明](../scripts/training/textturn_loss.md)。

`development_gate.minimum_success_rates`将正常接话、陈述接话、打断门槛各设1%。保留综合分高于初始化基线和误start／误stop回归容忍度0.02；开发集须完整执行、指标分母与基线相同且无未知。先按资格选模，再比较综合分，最终继续外部测试还须选中full阶段候选并重新满足全部条件；完整条件见[放行说明](../scripts/training/textturn_gate.md)。

pilot最多2000窗、full最多10000窗；所有窗口有正权重，只打乱轨迹顺序。单作业13800秒训练上限、显存22GiB、资产10GiB和报告2GiB不变，CPU8／RAM32GiB／单GPU由调度配置约束。此前超时与检查点保存流程不在本次用户指定的放行／损失修改范围；本次不启动训练或测试，TT-010仍保持未完成。
