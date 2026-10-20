# X2 服务测试

`tests/test_x2_asr_service.py` 用假在线引擎检查 `X2Service` 的会话协议，不依赖 GPU。

覆盖的行为：

- 暂停不会 finish 或 reset：`is_final=True` 的请求只作为提示，在线追加继续；
- 在线追加直接交付：`recognize` 返回假引擎的累计文本，没有前缀过滤或冲突处理；
- 只有 `end_stream=True` 才调用一次 `finish_async`，重复 `end_stream` 幂等；
- `close` 释放会话并 `abort`；
- 单活动会话约束：第二个 `create` 抛错，关闭后可再次创建；
- 非法 PCM（奇数长度 base64）抛 `ValueError`，未知会话抛 `KeyError`；
- `warmup` 按块提交真实 PCM、等待异步非空输出、EOF 收尾后释放独立会话；空输出、worker 异常、EOF 超时均失败且释放资源；空或全零预热输入拒绝执行。测量会话单独创建，不带入预热转写。

不覆盖：真实模型质量、在线交付延迟与长会话表现，这些必须在远端复测中测。

F1 回归还检查：音频请求返回后才 emit 的文本能被只读接口取回；重复读取不追加音频、不结束流；关闭后不能读取旧会话；HTTP 接口对未知会话和后台错误分别返回 404、500。
