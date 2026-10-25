# FDB：仅监控TextTurn的480ms与160ms测试

2026-10-25按用户纠正执行：FDB只监控TextTurn，不需要模拟回答。已移除助手正文和生成／播放生命周期；旧r1—r3保留为撤回记录，不混入本次结果。当前正式结果尚未交付，TT-005／006及TT-007保持实施中。

## 状态规则与输入

每条从Listen开始，只有start切Speak、stop回Listen、keep维持状态，不按时长自动复位。控制器读取完整在线ASR前缀；助手正文与历史为空，生成完成标志为null。Speak是控制器动作状态，不是实际播放。所有动作、输入及应用后状态均记录到trace。

同一固定TT-002候选，adapter SHA256为`32f5493835a1b21294a3b862e38da85f7d052bbc93dbf12a81c42436e14b5d17`。两次测试使用原冻结100条录音，Smooth50条、Pause50条及62个标注区间；正式条目、全部335候选、文件摘要和两条冒烟已分别核对完全一致，不重新抽样。

两次均以80ms包实时输入真实Nemotron。480ms聚合3个真实解码完成步骤，160ms每步形成完整周期；Turn Taking只拼接一次5秒静音，Pause不拼接。EOF排空和残窗不补观察。

| 周期 | 清单（远端dataset目录下） | SHA256 |
| --- | --- | --- |
| 480ms | `tt-005-006-fdb-action-r1/manifest.json` | `2f9da535d180187ed9c0fb3790f12cd751b8cb04d2e6c92001f23ba370c5a2c5` |
| 160ms | `tt-007-fdb-160ms-r1/manifest.json` | `242f34b755f2226343c40efe301f0ce18c65bcfc73b67e3120b4c50512d0dd4a` |

评分仍是最后ASR更新后的Speak比例、start比例、其中首次start平均等待拍数，以及更新前连续至少3周期Speak比例。等待同时报告毫秒；3周期名义覆盖分别为1440ms和480ms，不能按等时长直接比较。失败、未知和每臂50条计划分母保留，旧模拟回答协议与trace被新评分入口拒绝。

## 当前运行

冻结源码为`4e325bb`，远端worktree为`~/parathink-textturn/source/fdb-action-v1`。

| 工作 | run | 当前状态 |
| --- | --- | --- |
| TT-005／006，480ms | `tt-005-006-20261025-r4` | 作业`job-179290983788774807672-xuan-zhang`正在运行，两条真实ASR冒烟通过，正式回放至少完成5/100 |
| TT-007，160ms | `tt-007-20261025-r1` | 续接器已启动，状态为`waiting_for_predecessor`，等待r4结束；此时尚未提交160ms GPU作业 |

160ms续接状态和日志为`~/parathink-textturn/submit_logs/tt-007-20261025-r1.pipeline.json`及`.pipeline.log`。原480ms成功退出且释放GPU后自动重新核算预算并提交160ms；预算不足、原作业失败或调度错误明确停止，不并行申请。只有状态变为submitted并取得调度编号后才算160ms提交完成。

480ms前两条正式录音95和77的81次控制输入已核查：助手正文及历史均为空，生成完成标志为null，没有模拟生命周期事件。原始核查为run下`action_only_contract_audit.json`。这是运行合同检查，不是模型质量结论。

## 预算、验证和产物

r4提交前实际累计占卡18181秒：包含训练、旧评估、r1／r2及被撤回的r3。r3实际占卡1012秒；原8GPU小时剩10619秒。r4限制7200秒，160ms真正提交时按r4实际占卡重新核算，单次仍最多7200秒，不扩大总预算。

最多1×24GiB GPU、8CPU、32GiB、单活动作业、worker≤2；显存22GiB停止线、新增资产10GiB、报告2GiB、启动可用盘30GiB。续接器仅CPU单线程、2GiB地址空间、7900秒外层超时。模型、音频及conda环境只读复用。运行核查时显存4910MiB、资产约2.43GB、报告约0.41GB，监控正常。

12项本地conda测试通过，覆盖160ms单步、480ms聚合、ASR边界、拍数／毫秒换算、未知分母、同输入派生、旧协议隔离，以及状态不随时间自动复位。代码与对应中文说明已提交推送。

正式trace在各自run的`formal/traces`，进度为`formal/progress.json`；服务停止后自动输出`scoring/cases.csv`、`summary.json`、`intervals.json`与中文说明。新清单和r4预算已取回本地`artifacts/textturn/tt-005-006-20261025/`，按原始字节核对摘要，不重复将JSON入Git。旧运行记录见[撤回记录](../20261025-fdb-cross-dataset/README.md)。
