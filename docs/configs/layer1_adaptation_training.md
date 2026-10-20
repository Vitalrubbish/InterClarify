# 首轮正式适配配置

`configs/layer1_adaptation_training.yaml`为006首轮三臂共享参数，不替换005短跑配置。无类或方法。`arm`由启动器显式传入，仅允许T1/T2/T3；B0不执行训练。

窗口512、batch1/累积2、单epoch，共5,763步。沿用q/v LoRA更新范围、BF16与确定性计算；AdamW及线性warmup/衰减设置见027登记。每1,000步和最终步保留恢复检查点，输出上限5GiB、可用磁盘至少5GiB，GPU训练进程最长8小时。正式参数不表示已放行。
