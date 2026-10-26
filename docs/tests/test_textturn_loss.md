# 加权损失与完整轨迹边界测试

`tests/test_textturn_loss.py`的`TextTurnLossTests`用五组必要检查覆盖：70拍均有正权重且keep质量按轨迹封顶；单样本权重翻倍时损失及CPU梯度确实翻倍；固定归一化下梯度累积与批计算等价；轨迹打乱不删帧且预算不截断来源组；训练token注册保留旧四ID并加入输入finish。

使用已有conda和CPU显式执行，不运行GPU模型：`CUDA_VISIBLE_DEVICES='' conda run -n interclarify-dev python -m unittest discover -s tests -p test_textturn_loss.py -v`。测试不代替远端LoRA训练及质量验证。

2026-10-26增加3组动作平衡检查：三类有效质量均为N/3、基础行权重不被修改；有效加权CE等于三类平均CE的均值，逐样本累积与整批损失及梯度一致；缺失动作、份额非正／非有限或总和错误明确拒绝。历史无平衡配置的基础权重行为继续验证。
