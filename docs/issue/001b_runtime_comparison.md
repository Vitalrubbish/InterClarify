# Issue 001b：独立官方控制路径逐拍对照

状态：进行中。父任务：001。依赖资产核验；不依赖新 ASR 接入。

在固定官方源码上执行参考控制循环，集成侧使用真实 MicroTurnAssembler/RuntimeAdapter。分别报告同 prompt 单步、固定输出协议排错和独立历史自由回放；比较输入时钟、窗口、prompt IDs、生成 IDs、控制及正文、取消/reset。范围见 [远端任务单](001_remote_execution.md)，协议见 `configs/layer1_adaptation_protocol.yaml`。

必须记录首次差异。参考路径不得调用集成 prompt 构造器；AST prompt 片段审计不能替代完整控制循环。影响训练归因的差异未解释前阻断 006。独立 reference 的取样/插桩若影响行为，记录补丁和允许差异；无法执行的场景保持缺测，不标记通过。

完成后附双方时间线、源码摘要、退出码、报告路径及放行结论并归档；001 其他条件仍由父 issue 管理。


## 2026-10-18 早期结果（后续由001e修正）

原版AST控制体与集成路径在修复后四组固定输出（两种起拍×raw/完整词）51拍一致；真实权重raw协议8拍一致。完整词条件共同前7拍IDs一致，但截止时reference8拍、integration7拍，整轮退出1。原始时间线显示两路实际请求耗时及末窗拍数不同，必须继续分离逻辑时钟与传输/调度耗时；不能事后放宽既有标准。历史五例完整分片、same-prompt单步独立执行以及在途reset/cancel参考对照尚缺。报告见reports/layer1_training/issue001-runtime-20261018，001/006仍未放行。


## 最新结果

后续001e更正：旧8/7差异主要来自共享服务逐token重复计算词表大小，引发整体掉拍。修复后同一真实权重protocol轨迹raw两路13拍、完整词两路12拍，退出0；该差异已消除，剩余工作是历史五例完整分片、same-prompt单步独立执行和在途reset/cancel参考对照，不再把旧8/7列为当前未解释阻塞。

## 2026-10-18 验收清单核对

- [x] 独立官方 AST 控制循环与集成侧执行入口已实现。
- [x] 固定输出协议排错：两种起拍 × raw/完整词，合计 51 拍一致。
- [x] 单条 protocol 轨迹真实权重自由回放：first-nonempty 起拍，raw 13/13、完整词 12/12，逐拍 IDs、历史、控制及正文一致。
- [ ] 历史五例及规定输入变体、两种起拍、两种发布粒度的完整矩阵。
- [ ] 相同 prompt/历史的单步模式独立执行与结果留存。
- [ ] 在途 reset/cancel 的独立参考对照。
- [ ] 汇总全范围首次差异、允许差异、缺测与放行结论。

最新证据为 [issue001-validation-20261018](../../reports/layer1_training/issue001-validation-20261018/README.md)，实现提交 `368aa87`，远端作业 `job-179233595533938893476-xuan-zhang` 退出 0；早期失败见 [issue001-runtime-20261018](../../reports/layer1_training/issue001-runtime-20261018/README.md)。本项继续进行中，不能按局部复测成功归档或放行 006。
