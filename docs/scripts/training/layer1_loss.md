# 控制类别加权目标

`scripts/training/layer1_loss.py`实现036的五类控制权重，无产品服务或播放职责。无类。`target_statistics`只统计causal shift后的有效assistant目标，正文/EOS权重1；`weighted_causal_loss`对小段logits执行FP32交叉熵并在反向时重计算中间量，返回可微加权总和和普通CE/类别诊断。训练器使用全累积批次的权重总和作分母，不分别平均micro-batch。masked user/header/history/padding均不参与。
