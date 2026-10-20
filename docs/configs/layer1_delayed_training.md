# 延后启动全量训练配置

`configs/layer1_delayed_training.yaml` 为独立第三轮条件，无类/方法。沿用第二轮优化器、完整官方初始化、已有112个q/v LoRA及冻结embedding/head；只将数据切换到040a，配置1235步、warmup124、每206步保存。loss为control_weighted_ce，五类权重1/10/5/2/1，chunk64。单卡2048、batch1/累积2、1epoch；最后单序列按实际权重归一化。训练5GiB/8小时/保留5GiB空闲。
