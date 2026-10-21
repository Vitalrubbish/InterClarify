# 延后句读1k训练配置

`configs/layer1_asr_training.yaml`在077索引生成后冻结，purpose为`issue078_asr_punctuation`，条件为`ASR_R4_delayed_punctuation`。无类/方法。除按实际序列重算单epoch步数、10%warmup、约1/6保存点和空闲盘20GiB外，优化器、加权loss、batch/累积及精度策略沿用040。
