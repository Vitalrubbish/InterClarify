# 短延迟对照契约测试

`tests/test_xturnix_short_latency.py` 使用合成到达事件检查旧版本分数隔离、新文字重置等待、进度异常/健康过期/空文字的拒绝行为，以及失败分母和校准/评估选择隔离。

`ShortLatencyContractTest` 的七个测试只覆盖关键决策契约，包括用显式事件闸门检查单在途/最新待处理替换，以及用模拟网络检查临时失败重试与字节上限；不加载模型、不联网、不产生真实 ASR 或延迟成绩。运行：`conda run -n interclarify-dev python -m unittest tests.test_xturnix_short_latency -v`。
