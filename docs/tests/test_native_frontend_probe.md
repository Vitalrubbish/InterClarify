# NTF-018预热与IPC检查

对应`tests/test_native_frontend_probe.py`，使用官方真实控制方法和微型CPU依赖，不加载GPU权重。`ProbeTests`验证仅预热可关闭墙钟保护、未读PCM上限仍有效、预热Context与正式Context隔离、清理后KV／回调释放、真实时钟持续供音、EOF部分批次和未覆盖分支拒绝放行；原生对照另比较新增观察前后的实际输入／输出。

`IPCTests`验证消息容量、明确失败、1680采样窗口摘要、防止读取未发送音频、跨边界回执中的WAIT／EOS闭合正文和帧号连续。实际socketpair验证消息编码，轻量worker验证80ms往返接口；不以它冒充远端跨conda权重加载成功。

续做增加离线审计检查：读取实际轻量前端产生的完整逐帧证据，确认原记录通过后，注入伪造EOS会失败；缺失完整矩阵目录也不能放行019。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_native_frontend_probe.py -v`。完整回归仍由`python -m unittest discover -s tests -q`执行。真实预热覆盖、GPU延迟与资源门槛必须在远端验收。
