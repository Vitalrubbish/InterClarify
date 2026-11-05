# test_score_fdb30_half_duplex.py

`TimingRuleTests` 保留旧全量评测测试中仍适用于当前基线的评分边界，直接验证 `score_fdb30_half_duplex` 实际导入的 `behavior`，不依赖已删除的 DuplexCascade 重放或评分模块。

`test_turn_thresholds_and_negative_latency` 检查三词／四词、恰好一秒与提前输出的零截断；`test_missing_response_has_no_latency` 检查无响应保持 TOR=0 且延迟为空。测试使用固定时间戳，不加载识别模型，也不代替远端官方评分交叉核对。
