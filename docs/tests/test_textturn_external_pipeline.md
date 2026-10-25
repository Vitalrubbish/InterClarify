# TT-011 必要契约检查

对应 `tests/test_textturn_external_pipeline.py`。`ExternalTests`用短前缀和临时JSON产物覆盖五token／已学习行身份、播放完成后finish且只闭合一次、stop后迟到finish、自然结束后的过期动作、审核前缀绑定、调度输出解析失败与未知提交回执不重复提交。最后核对自然结束不会变成stop成功。

这些是CPU契约检查，无真实模型或GPU；真实服务接口和FDB录音冒烟只在远端调度节点执行，不计正式样本分母。
