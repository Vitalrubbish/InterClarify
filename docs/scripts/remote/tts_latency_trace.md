# TTS 结构化时间线

`tts_latency_trace.py` 为实验提供线程隔离的 request/response 上下文、单调时钟事件与 JSONL 落盘。`trace_scope` 绑定关联 ID，`emit` 记录事件，`span` 记录起止及失败；关闭时不写文件。进程 ID 与时钟域必须保留，不能直接减去客户端时间戳。落盘失败应使实验失败，避免悄悄丢失证据。

仅记录观测，不执行播放或话轮动作。GPU 时间仍由现有 CUDA event 指标采集，JSONL 的 span 是 CPU 墙钟，不能宣称为 kernel 时间。
