# UltraChat 重测边界测试

对应 `tests/test_textturn_ultrachat_retest.py`。`RetestTests`使用字符级替身tokenizer验证时间与状态，不调用模型或服务器。五项测试覆盖排队时按名义时间发布多个正文块且stop不泄漏未来正文、start仅提交请求看到的用户前缀、自然完成后拒绝迟到stop、严格960ms边界和不以末次更新后静音凑重叠。

另以真实时钟延迟替身推理，验证待处理观察合并时正文仍独立按周期发布。

本地使用现有interclarify-dev conda环境执行。真实候选、tokenizer、长输入及远端资源行为仍以服务器运行证据为准。
