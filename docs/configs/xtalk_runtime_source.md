# X-Talk运行源码版本

`xtalk_runtime_source.json`登记保留的X-Talk工程框架仓库、分支与完整提交，用于后续源码冻结和报告追溯；该文件不加载模型或启动服务。当前基线的模型、TTS、线程与评测口径见 [运行基线](../runtime_baseline.md)。旧 DuplexCascade 英文运行配置及其服务已删除；本文件继续登记独立框架源码，不表示当前半双工评测已集成到框架。

当前为 `origin/dev` 的 `ca9b23c`：保留 300/1200ms 分段、会话 KV 请求/释放与延迟观测，并把 X2 专用传输重命名为通用 `ContinuousStreamingASRClient`。运行行为与 `d6dc3bf` 等价；旧 X2/Qwen3 fork 文档与测试已移除。

正式提交替代临时 `xtalk_latency_defaults.patch`。发布后完整链路时延未重测，性能结论以当前运行配置和后续实测为准。
