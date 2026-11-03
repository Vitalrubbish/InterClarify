# NTF-018预热与IPC检查

对应`tests/test_native_frontend_probe.py`，使用官方真实控制方法和微型CPU依赖，不加载GPU权重。`ProbeTests`按NTF-030验证正式／预热模式均允许超过800ms的积压与12800采样未读量，仍执行4MiB限制；覆盖单／双路、预热Context与正式Context隔离、清理后KV／回调释放、真实时钟持续供音、EOF部分批次和未覆盖分支拒绝放行。离线审计同样允许长延迟而拒绝PCM容量越界；原生对照另比较新增观察前后的实际输入／输出。

`IPCTests`验证消息容量、明确失败、1680采样窗口摘要、防止读取未发送音频、跨边界回执中的WAIT／EOS闭合正文和帧号连续。实际socketpair验证消息编码，轻量worker验证80ms往返接口；不以它冒充远端跨conda权重加载成功。

续做增加离线审计检查：读取实际轻量前端产生的完整逐帧证据，确认原记录通过后，注入伪造EOS会失败；缺失完整矩阵目录也不能放行019。

输入准备修正检查覆盖低幅度真实形状语音的确定性增益、PCM16量化、峰值限制、既定静音尾部，以及全静音拒绝；它只验证输入处理，不预言真实模型一定产生complete或文字修订。

单路完成计数修正用真实时钟及重复原生reset验证：允许因重新供给PCM产生更多调用，EOF尾部及容量检查保持；双路批次数精确要求继续由原有检查约束。原800ms停止条件已按NTF-030取消。

019入口增加未通过／摘要错误的验收证据不得启动正式套件检查；有效门槛才能选择全部30条，有限预热条件不得运行正式套件。gzip证据与普通证据读取后必须完全一致。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_native_frontend_probe.py -v`。完整回归仍由`python -m unittest discover -s tests -q`执行。真实预热覆盖、GPU延迟与资源门槛必须在远端验收。
