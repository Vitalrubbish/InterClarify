# Issue 001：冻结官方输入契约、基线与验收口径

状态：完成，2026-10-19。优先级：P0。官方输入与控制对照门禁通过；训练仍未放行，004/005 和 007 开训前准备继续执行。

## 冻结范围

按固定 DuplexCascade [server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422-L499)接收 Kyutai Word，逐词 strip、每拍空格连接；首个非空 Word 后 600ms 首拍，发布 checkpoint/tokenizer、BF16、64-token 贪心和官方结束 ID。只比较历史五例原样输入，不展开时钟、发布粒度或句读矩阵。

双方消费同一份真实 Word 事件并独立生成历史。产品仍为 Nemotron/Kokoro；本项不要求未适配权重接话率达标，也不替代真实产品迁移、音频、训练恢复或 FDB 验收。

## 完成证据

- [x] 资产与实际 token IDs 已由 001a 冻结，官方代码/权重、Qwen2、Nemotron、Kokoro、Kyutai 及 UltraChat 许可来源和当前使用边界已核对，见验收报告。
- [x] 历史五例原始记录只有 token/累计文本，已用冻结 Rust 服务补采原生 Word，词数 11/11/14/16/16；原始消息、到达时间、音频和捕获摘要齐全。
- [x] 现有比较器直接使用 Word 缓冲，删除 RawDeltaBuffer、超时残词发布及配置矩阵，不新增控制器。
- [x] 五例真实权重自由回放共 136 拍：28/26/26/28/28，两路 prompt IDs、原始生成 IDs、提交历史、控制及正文首次差异均无，作业退出 0。
- [x] 远端 7 项测试通过，含在途取消、关闭后无新提交和新会话历史隔离；实际 GPU 释放与设备播放仍由组件/音频验收负责。
- [x] 保留历史接话 0/5 及失败日志，登记三组继续训练、UltraChat 规模、种子、最多两轮和 72 GPU 小时上限；本轮未启动训练。

结果、源码摘要、许可、完整 IDs 与退出码见 [issue001-word-20261019](../../../reports/layer1_training/issue001-word-20261019/README.md)。采集作业 `job-179234084264647775229-xuan-zhang`、对照作业 `job-179234101532068397696-xuan-zhang` 均退出 0，实际运行字节以报告 source.sha256 为准。

001b 和本任务完成归档。001a/c/d/e 的已有修复证据继续保留；旧 raw/有界 complete_word 只作诊断，不改写历史结果。协议仅将 `issue001_runtime_comparison` 设为 passed，`training_released` 仍为 false。
