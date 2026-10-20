# `tests/test_xtalk_link_check.py`

用异步模拟事件验证最小联调驱动的失败判据与响应 ID 关联。覆盖轮次超时、旧响应结束、新响应完成、插话停止 ID 及服务 error；不启动 GPU 或采集新数据。`LinkCheckTests` 对 `_run_turn`、`_run_barge_in`、`_receive` 和 `_wait_for` 使用确定性事件，远端实际连接另行复测。


X2 duplex 的会话能力 `acoustic_vad_enabled=false` 由服务端按连续 ASR 能力确定。禁用声学 VAD 检测、声学开始/结束信号及 pause/resume 调度；保持会话级连续 PCM 与每拍文本读取。浏览器在握手后创建关闭 VAD 的输入设备，旧客户端声学信号在网关被忽略。Qwen 与内部文本提交边界保持原行为。验证覆盖残留 VAD 信号不触发 ASR 控制、静音和播放期间连续输入、同一解码会话及握手能力。
