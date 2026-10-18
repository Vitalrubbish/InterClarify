# Issue 001b：独立官方控制路径逐拍对照

状态：进行中。父任务：001。依赖资产核验；不依赖新 ASR 接入。

在固定官方源码上执行参考控制循环，集成侧使用真实 MicroTurnAssembler/RuntimeAdapter。分别报告同 prompt 单步、固定输出协议排错和独立历史自由回放；比较输入时钟、窗口、prompt IDs、生成 IDs、控制及正文、取消/reset。范围见 [远端任务单](001_remote_execution.md)，协议见 `configs/layer1_adaptation_protocol.yaml`。

必须记录首次差异。参考路径不得调用集成 prompt 构造器；AST prompt 片段审计不能替代完整控制循环。影响训练归因的差异未解释前阻断 006。独立 reference 的取样/插桩若影响行为，记录补丁和允许差异；无法执行的场景保持缺测，不标记通过。

完成后附双方时间线、源码摘要、退出码、报告路径及放行结论并归档；001 其他条件仍由父 issue 管理。


## 2026-10-18 当前结果

原版AST控制体与集成路径在修复后四组固定输出（两种起拍×raw/完整词）51拍一致；真实权重raw协议8拍一致。完整词条件共同前7拍IDs一致，但截止时reference8拍、integration7拍，整轮退出1。原始时间线显示两路实际请求耗时及末窗拍数不同，必须继续分离逻辑时钟与传输/调度耗时；不能事后放宽既有标准。历史五例完整分片、same-prompt单步独立执行以及在途reset/cancel参考对照尚缺。报告见reports/layer1_training/issue001-runtime-20261018，001/006仍未放行。
