# 160ms数据边界测试

`tests/test_textturn_duplex_dataset.py`的小型tokenizer仅用于CPU合同检查。`DuplexDatasetTests`覆盖六组边界：随机句中停顿可复现、全部暂停keep及160ms时钟；用户末尾句读删除并保留小数缩写；歧义keep到首个非附和stop及迟到回调；随机附和替换原控制拍、独立归档且继续Speak；专用finish单ID、保存重载、输入掩码和一次消费；陈述／疑问start对照、助手3／3／2速率、重复更新及截断；同刻播放先完成时不再stop、播放错误不冒充finish、附和跨播放结束继续到达及空白片段不丢失。

测试中将概率设为0或1是为了覆盖边界，正式配置仍为停顿0.20和附和0.01，不是参数搜索。不加载模型，不替代真实Nemotron或停播测试。已有conda执行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_textturn_duplex_dataset.py -v`。
