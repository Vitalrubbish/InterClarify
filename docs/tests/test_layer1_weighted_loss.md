# 加权 loss 与最终候选重载

`tests/test_layer1_weighted_loss.py` 在具备 torch 的 conda 中检查五类控制加权 CE：与直接 CE 的数值/梯度等价、全局权重分母、chunked 计算、padding/history mask、空目标拒收，以及恢复身份变化在参数复制前被拒绝。

末尾用例构造最终 `T2_R3_delayed_start` 检查点，验证干净进程重载返回可服务身份、复现生成 IDs，并拒绝非最终 epoch 或未完成训练。无 GPU 权重下载；真实 7B 候选仍在远端单卡执行。旧 036 对齐配置契约测试已随旧设计删除。
