# 延后句读1k数据配置

`configs/layer1_asr_data.yaml`沿用040a种子、1000/200/300来源切分和事件参数，只新增`generation.asr_surface=delayed_punctuation_v1`；不改变优化器。无类/方法。构建入口要求相对原配置只有该视图声明不同，重新编码2048窗口，不沿用旧步数。
