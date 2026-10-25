# 完整轨迹的动作损失权重

`scripts/training/textturn_loss.py`只负责损失元数据及训练顺序，不生成话轮标签。`assign_loss_weights`按scenario_id、状态和类别统计keep数K，每拍权重min(1,2/K)；start／stop各2。所有窗口权重为正，同组重复keep总质量最多2，不删除后期停顿、附和或尾窗。

`complete_trajectory_groups`要求快照编号从0连续递增、时钟严格递增且没有排除帧；`trajectory_order`每轮只打乱轨迹次序、内部时序不动。`weight_summary`提供阶段固定平均权重、动作质量及范围。`weighted_action_loss`先得到逐样本交叉熵，再乘正权重、除以阶段固定平均权重和样本数；梯度累积只按实际组样本数平均，不按当前组权重重新归一化，因此单样本下权重不会抵消。

权重只在训练损失使用，不进入prompt。finish及正文输入label仍为-100，模型只预测keep/start/stop。此方案控制重复窗口暴露，不保证最优误动作率；质量仍由开发集和后续独立验证判断。
