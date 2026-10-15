# X2 服务测试

`tests/test_x2_asr_service.py` 用假在线引擎检查 `X2Service` 的会话协议，不依赖 GPU。

覆盖的行为：

- 暂停不会 finish 或 reset：`is_final=True` 的请求只作为提示，在线追加继续；
- 在线追加直接交付：`recognize` 返回假引擎的累计文本，没有前缀过滤或冲突处理；
- 只有 `end_stream=True` 才调用一次 `finish_async`，重复 `end_stream` 幂等；
- `close` 释放会话并 `abort`；
- 单活动会话约束：第二个 `create` 抛错，关闭后可再次创建；
- 非法 PCM（奇数长度 base64）抛 `ValueError`，未知会话抛 `KeyError`；
- `warmup` 只用一个会话（创建 → 追加静音 → 关闭），结束后不残留活动会话，随后仍可正常创建并识别。

不覆盖：真实模型质量、在线交付延迟与长会话表现，这些必须在远端复测中测。
