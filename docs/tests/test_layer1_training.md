# 有限训练状态测试

`tests/test_layer1_training.py`验证assistant监督边界、历史/user/header屏蔽、padding、单epoch采样边界及数据损坏拒绝。`SupervisionTests`不加载模型，在本地conda运行；`StateTests`在远端训练conda用小型真实张量验证AdamW、scheduler、随机dropout、Python/NumPy/torch RNG与游标恢复，逐项摘要要求完全一致，并拒绝未清空梯度的中途checkpoint。

这些契约测试不能代替025的真实4090官方模型更新及独立进程恢复对照。
