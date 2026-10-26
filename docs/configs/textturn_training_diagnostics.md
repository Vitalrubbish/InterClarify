# TextTurn诊断配置

`configs/textturn_training_diagnostics.json`冻结检查点来源、开发探针来源数和三个优化对照臂，复用正式训练的模型及优化器参数。`max_wall_seconds`只限制诊断作业，正式训练的null时限不变；每臂两轮是有限学习机制测试。

开发探针固定20来源，正例与相邻负例用于诊断，不能替代完整机会评分。完整pilot评估及梯度审计在inspect阶段，compare阶段逐轮评估相同边界探针。所有原始结果进入独立run目录。

确认阶段使用后续20个开发来源的完整轨迹，来源集合与比较探针不重叠；`confirmation_sources`冻结该数量，不读取预测挑选来源。
