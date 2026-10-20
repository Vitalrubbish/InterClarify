# 对齐契约测试

`tests/test_layer1_alignment.py`中的`AlignmentConfigTests`验证独立配置、122步warmup、原学习率/白名单/曝光、资源门禁和短跑不可服务；`WeightedLossTests`以小张量人工计算参考验证causal shift、目标mask、五类权重、正文/EOS、全累积归一化及梯度一致性。包含普通CE诊断和类别计数/NLL，空目标与损坏配置拒绝。真实模型、CUDA峰值、独立进程恢复和生成复现由远端脚本验证。

补充测试：用户豁免只放行正式单epoch入口，不允许扩大参数、数据或优化器范围；没有豁免的路径仍要求真实短跑证据。
