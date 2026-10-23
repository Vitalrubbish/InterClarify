# XTurnix 工作单

更新：2026-10-24。当前路线为 **ASR 时间信息＋冻结 XTurnix 的无训练 Listen 控制**。用户明确要求先利用 ASR 时间、不训练模型；已将 XTX-008、009、011—013 搁置归档，未完成内容不计为验收通过。当前实施入口为 [XTX-014](xtx_014_asr_time_control.md)，方案见[ASR 时间无训练路线](../../dev/XTurnix/asr_time_control.md)。随后用户要求检查并尝试原生 pause，XTX-014 正在进行使用核查与机制诊断；完整 ASR 时间适配尚未完成。

## 当前工作

| 编号 | 工作单 | 状态与依赖 |
| --- | --- | --- |
| XTX-014 | [ASR 时间观测与无训练 Listen 控制](xtx_014_asr_time_control.md) | 进行中；先核查并尝试原生 pause，完整 ASR 时间适配待验证 |
| XTX-010 | [未训练基线、校准与评分](xtx_010_control_baseline_calibration.md) | Listen 纯文本阶段已完成，保留为对照；Speak 校准继续后置，本项整体未完成 |

[Listen 校准结果](../../../reports/xturnix_training/20261023-listen-calibration/README.md)：留出误抢话 10.78%→5.39%，末端召回 44.31%→28.74%，未达预设 5% 工作点，不采用该阈值上线。新路线先使用文字无增量时长与 ASR 进度，在同一控制策略内联合语义分数选择动作，不更新权重或向官方 prompt 追加未验证时间字段。

## 当前共同边界

- 先验证 Listen 下 keep/start；Speak 下 keep/stop、CoT、Layer 0/1/2、TTS 与完整播放接入不在本轮，现役 DuplexCascade 不切换。
- ASR 无增量时长作为带延迟的静默估计；音频接收、消费、健康和输入版本另记，链路停滞不冒充静默。消费进度不自动等于解码完成进度；首次文字到达前计时缺失。
- 新文字更新语义分数，时间跨越冻结区间可复用同版本分数重判；单会话最多一个在途模型请求和一个待处理最新观察，不用旧前缀分数提交新前缀动作。
- 输出仍经唯一仲裁执行点与单一 TTS 播放所有权；当前只记影子动作，已听内容不可撤销，不新增 Layer 3 或第二条执行路径。
- 配置仅在开发集选择，独立评测前冻结。此前已阅的留出集仅作回归/探索，不再当作新独立测试；FLEURS/FDB 不用于新路线选参，不恢复取消作业。
- 本地与远端复用 conda；真实模型验证仅在远端调度作业。最多 1×24 GiB GPU、8 CPU、32 GiB RAM、batch=1、一个活动作业、单作业≤4 小时；下载与评分 worker≤2。
- 启动空闲盘≥30 GiB，累计新增资产≤10 GiB、trace/报告≤2 GiB；承接既有 GPU 使用和资产记录，不因路线更名重置预算，不自动扩容。
- 实现按实际文件维护 `docs` 同路径中文说明，测试只覆盖关键契约；每次运行保留独立 run_id、哈希、配置、资源及退出证据。

<a id="vad-assisted-training"></a>
<a id="训练阶段共同边界"></a>

## 已归档的分析与训练路线

本节保留旧锚点供历史文档引用。训练相关项因用户选择当前无训练路线而搁置归档，不能计作已完成，也不再作为 XTX-014 的前置。原方案与候选训练预算见[历史方法文档](../../dev/XTurnix/training_feasibility.md)，不会自动恢复。

| 编号 | 工作单 | 归档性质 |
| --- | --- | --- |
| XTX-007 | [训练可行性分析与讨论](../archive/XTurnix/xtx_007_training_feasibility.md) | 已完成分析与讨论，归档不代表训练可行性通过 |
| XTX-008 | [VAD 输入与训练环境](../archive/XTurnix/xtx_008_vad_input_contract.md) | 搁置归档，未实施 |
| XTX-009 | [四类训练数据审核冻结](../archive/XTurnix/xtx_009_training_data_freeze.md) | 搁置归档；48 会话辅助审核已完成，正式试标和冻结未完成 |
| XTX-011 | [LoRA 入口与资源探针](../archive/XTurnix/xtx_011_lora_resource_probe.md) | 搁置归档，未实施 |
| XTX-012 | [受限 LoRA 试训](../archive/XTurnix/xtx_012_lora_pilot_training.md) | 搁置归档，未实施 |
| XTX-013 | [训练后独立验证](../archive/XTurnix/xtx_013_independent_training_evaluation.md) | 搁置归档，未实施 |

<a id="fleurs-evaluation"></a>

## XTX-001—006：既有两组件测试

| 编号 | 内容与证据 | 状态 |
| --- | --- | --- |
| XTX-001 | [FLEURS 输入与历史 ASR 基线](../../../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md) | 已完成并归档 |
| XTX-002 | [组件服务及控制协议冻结](../../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md) | 已完成并归档 |
| XTX-003 | [真实时钟回放与事件采集](../../../reports/xturnix_fleurs/20261023-xtx-003-replay/README.md) | 已完成并归档 |
| XTX-004 | [独立评分与链路估计](../../../reports/xturnix_fleurs/20261023-xtx-004-scoring/README.md) | 已完成并归档 |
| XTX-005 | [A10 远端入口与 5 条冒烟](../../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md) | 已完成并归档；0/5 start 仅作诊断 |
| XTX-006 | 正式 100 条回放；另见[pause 诊断](../../../reports/xturnix_fleurs/20261023-pause-token-probe/README.md) | 正式作业已取消，未产生正式成绩 |

既有协议继续冻结：固定 100 test＋1 dev、Nemotron EN160＋PT、80ms 传输、Listen 影子动作、5 秒尾窗与独立 EOF 排空。新路线不改写旧配置、评分或报告。历史 ASR 413.582852ms 只作典型开销估计，不当作固定延迟、整体 P95 或用户可听接话时间。

全局入口见[工作单管理](../README.md)，职责与长期研究范围见[研究主文档](../../research_design.md)，当前顺序见[工程实施计划](../../engineering_implementation.md)。
