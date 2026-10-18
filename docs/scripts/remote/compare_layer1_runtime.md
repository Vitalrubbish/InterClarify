# 独立官方控制循环对照

`scripts/remote/compare_layer1_runtime.py` 用于诊断官方控制循环与现有 X-Talk Assembler/RuntimeAdapter 的执行差异。`load_reference` 校验固定 server.py 摘要，提取 prepare_llm_tokens、TokenQueueStreamer 和 llm_tick_task；`ReferenceKernel` 将原始 prompt IDs 发送到同一冻结 GPU 服务，绕过集成 prompt renderer。`Tensor` 只适配传输形状，`Tokenizer` 读取发布 tokenizer。

`reference` 执行参考循环，`integrated` 驱动现有总线与运行时，各自生成历史。共同内核先预热，原版 join 后增加整拍提交观测以避免 EOS 消费前截断。`compare` 定位 prompt/生成 IDs、历史、控制、停播或正文的首个差异；`run` 写逐例时间线和覆盖缺口，支持 cases/modes 分片。

当前输入尚未复现官方 Word 协议：`RawDeltaBuffer` 将 raw 字符后缀在窗内拼接成一个伪 Word；`complete_word_events` 在空格处发布，最长暂存 160ms 后仍可释放残词。两者都是诊断输入。官方 [server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422-L499)直接消费 Kyutai Word 并逐词 strip、每拍空格连接，不能把上述模式直接称为官方输入。

001b 待在本文件直接接入保留到达时间的真实 Word 事件并保留官方缓冲语义；无需新增通用模式框架。必验只使用官方首 Word 起拍、600ms 和五例原样样本，其他模式仅按需排错。当前 `fully_aligned: false` 反映完整官方语音链路等覆盖限制，单次退出 0 也只证明声明的诊断范围，最终放行需逐例结果、集成生命周期与资产证据。
