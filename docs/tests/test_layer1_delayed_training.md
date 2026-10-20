# 延后启动训练契约回归

`tests/test_layer1_delayed_training.py` 在临时目录冻结新索引与数据 audit，检查完整加权配置可放行、旧数据摘要/旧索引拒收、用户授权必须匹配且不能训练短 epoch、普通 CE 和权重变化不得进入最终条件。测试同时核对训练后计划只登记 `T2_R3_delayed_start` 且不自动提交 FDB。

加权 loss 的数值/梯度等价与最终候选重载由 [test_layer1_weighted_loss.py](test_layer1_weighted_loss.md) 在有 torch 的 conda 中执行。测试无 GPU 或模型权重下载。
