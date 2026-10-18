# Issue 001b：按官方 Word 输入对照控制路径

状态：进行中。父任务：[001](001_input_contract_and_baseline.md)。不依赖新 ASR 接入。

## 输入与执行

参考执行固定提交的官方控制循环，集成执行现有 MicroTurnAssembler/RuntimeAdapter。共同输入为同一份带到达时间的 Kyutai Word 事件：逐词 strip，每拍用空格连接；首个非空 Word 起拍、600ms、BF16、64-token 贪心、原样句读。只使用历史五例，不展开配置矩阵。

官方依据为 [server.py 的接收和分拍逻辑](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422-L499)。现有 RawDeltaBuffer 将字符后缀拼成一个伪 Word，`complete_word_events` 又允许 160ms 超时释放残词，两者都不能作为官方 Word 协议的完成证据。优先复用真实已保存 Word 事件；若缺失，只补采所需五例，不重新选型 ASR。

## 任务与验收

- [ ] 冻结五例 Word 原始事件、到达时间、参考源码和模型摘要。
- [ ] 直接修改现有比较器的输入读取与缓冲，保留官方词事件语义；不新增通用模式框架或复制控制循环。同步实现文档，核验跨拍空格和词内片段不被当作独立 Word。
- [ ] 双方独立历史连续自由回放，比较窗口、prompt IDs、原始生成 IDs、控制动作和正文；输出首个差异及原因，必要范围缺测不算通过。
- [ ] 集成侧在途 reset/cancel 核对旧请求、历史和响应代际隔离，复用已有测试；无需官方提供同名接口。
- [ ] 保存逐例时间线、退出码、源码摘要、允许差异和 go/revise/block 结论，再交父任务审核。

仅在出现具体差异时运行同 prompt 单步或固定输出排错。比较器的 `fully_aligned` 还包含完整官方语音链路等覆盖限制，既不能单独据此否定本项，也不能只凭退出 0 放行。

## 已有证据

[阶段报告](../../reports/layer1_training/issue001-runtime-20261018/README.md)包含固定输出 51 拍；[最新复测](../../reports/layer1_training/issue001-validation-20261018/README.md)的 protocol raw 13/13、complete_word 12/12 一致，作业 `job-179233595533938893476-xuan-zhang` 退出 0，实现提交 `368aa87`。这些证明已测诊断输入下的修复效果，旧 8/7 耗时问题已消除；没有原始 Word 输入证据，不升级为官方输入验收。历史报告原样保留，本任务尚不归档。
