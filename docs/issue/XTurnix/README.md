# XTurnix 工作单

更新：2026-10-23。XTX-001 已完成远端数据冻结与复核，XTX-002 已完成远端环境/协议冻结与 dev 验证并归档，XTX-003—006 待实施。本轮不表示正式回放、评分或模型质量测试已完成。总范围见[工程实施计划](../../engineering_implementation.md)，全局入口见[工作单管理](../README.md)。

## 工作单与依赖

| 编号 | 工作单 | 依赖 | 状态 |
| --- | --- | --- | --- |
| XTX-001 | 固定 FLEURS 输入与历史 ASR 基线（[证据](../../../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)） | 无 | 已完成并归档 |
| XTX-002 | Nemotron/XTurnix 服务及控制协议冻结（[证据](../../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)） | XTX-001 | 已完成并归档 |
| XTX-003 | [真实时钟回放与事件采集](xtx_003_streaming_replay.md) | XTX-001、002 | 待实施 |
| XTX-004 | [独立评分与链路估计](xtx_004_independent_metrics.md) | XTX-001、003 | 待实施 |
| XTX-005 | [远端作业入口与 5 条冒烟](xtx_005_remote_smoke.md) | XTX-001—004 | 待实施 |
| XTX-006 | [100 条正式回放与报告](xtx_006_formal_evaluation.md) | XTX-005，复用前序冻结产物 | 待实施 |

按依赖推进；XTX-003 和 XTX-004 共用测试入口，但分别负责在线采集和离线评分，不混淆模型执行与指标计算。少量测试随对应实现交付，不额外拆分为大量测试工作单。

## 共同边界

- 固定 100 test＋1 dev；正式采用 Nemotron EN160＋XTurnix-PT、80ms 音频传输、Listen 条件影子决策、5 秒在线静音尾窗及独立 EOF 排空。
- 主测最后 ASR 词汇增量可见到有效 start 返回；最后词汇位置只能事后评分，不能进入在线触发。提前、旧前缀迟到、窗外和 EOF 后 start 分别保留。
- 报告全部计划分母、失败与 null；历史 413.582852ms 仅作 ASR 典型开销估计，不冒充实测末词延迟、整体 P95、FDB TOR 或可听回复延迟。
- 本轮不运行 Layer 1/2、TTS、播放器或训练，不恢复已取消的 FDB 测试；不改现役模型环境和单一播放所有权。
- 真实模型测试在远端 conda 作业执行。最多 1×24GiB GPU、8 CPU、32GiB RAM、batch=1、单作业/单录音、4 小时；下载并发≤2、评分 worker≤2。新增资产累计≤10GiB，trace/结果≤2GiB，启动可用盘≥30GiB，触限不自动扩容。
- 每项完成并满足验收后立即归档至 `docs/issue/archive/XTurnix/`，同时更新本页及全局入口的链接和状态；归档不删除证据，不能提前标记已完成。
