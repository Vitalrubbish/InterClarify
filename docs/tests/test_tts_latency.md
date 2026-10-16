# TTS 实验逻辑回归

`tests/test_tts_latency.py` 使用假 Session、固定 logits 和内存音频验证真实风险：批次余量不等待新 push、首批上限、EOS 与取消丢弃、未满 prefill 门槛、队列关联 ID、有效历史 0/1/49/50/超窗、负 logit 和 token 0、模式分组、无音频/失败分母、RMS 起点与虚拟缓冲断流。无需 GPU，torch 可用时在 CPU 检查惩罚数学；真实编译、音质和采样数值仍须远端验收。

`ProtocolTests` 用本地 WebSocket 协议夹具验证固定增量顺序、显式音色路径、完成事件、WAV/时间线落盘，以及服务无完成事件时超时保留失败。夹具通过只证明工具能工作，不构成固定 adapter 真机接入或 GPU 性能验收。

`ServicePatchTests` 覆盖实际包装器的 start 构造/余量推进与取消绑定，并在服务供音等待中触发 close，确认最后 PCM 提交检查阻止旧数据入队。

当前本地验证：`paratalker-dev` 全量 91 项（67 通过、24 跳过）；`vllm-bench` TTS 相关 42 项（37 通过、5 项真实上游依赖跳过）。后者 torch 与远端版本不同，只代表 CPU 逻辑与工具协议验证。
