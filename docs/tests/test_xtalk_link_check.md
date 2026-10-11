# `tests/test_xtalk_link_check.py`

用异步模拟事件验证最小联调驱动的失败判据与响应 ID 关联。覆盖轮次超时、旧响应结束、新响应完成、插话停止 ID 及服务 error；不启动 GPU 或采集新数据。`LinkCheckTests` 对 `_run_turn`、`_run_barge_in`、`_receive` 和 `_wait_for` 使用确定性事件，远端实际连接另行复测。
