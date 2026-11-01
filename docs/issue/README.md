# 工作单管理

更新：2026-11-01。当前确认的下一步路线改为 **Nemotron 作为唯一教师文本、取消 SenseVoice 滑窗、按方案 A 以整块缓冲对齐训练序列**，拆为 [NTF-007](NTF-007.md)／[NTF-008](NTF-008.md)／[NTF-009](NTF-009.md)，只测同卡、不训练。此前 **SoulX＋SenseVoice控制、Nemotron正文与缓存状态配对发布**已完成功能与固定实验，实时及整体质量未通过，见[研究方案](../research_design.md)与[工程计划](../engineering_implementation.md)。TextTurn、VoxTurn、XTurnix 三条历史路线已按用户指令归档：路线文档移至[归档区](../archive/dev/README.md)，对应实现移至 [archive/](../../archive/README.md)，历史工作单保留在本地 `docs/issue/archive/`（不进入 Git）。

当前用户已授权 Nemotron Teacher Forcing 接入与 FDB 三轴固定小样本实验。下游 Agent 尚未切换到 SoulX，旧 Nemotron 公开英文集方案和旧文本控制器合同只作为历史设计，不恢复作业。

当前活动工作单按顺序为 [NTF-006](NTF-006.md) → [NTF-008](NTF-008.md) → [NTF-009](NTF-009.md)。NTF-006 本地实现完成，远端字段验收并入 NTF-008；NTF-007 已完成并归档（append-only 文本路径，本地、远端三轴预检3/3）；NTF-008 本地完成（音频embedding有界缓冲、首块不特判、字段接入、complete不重识别），待远端预检；009 尚未实施。

NTF-007 已完成并归档至本地 `archive/`：删除教师文本门控、`_revise()`、KV检查点、输入账本和三项缓存上限，改为增量追加与尾部重编码审计。远端 `ntf007-teacher-smoke-20261101-r1` 三轴预检3/3、退出0，逐帧确认控制文字前缀追加、token累计一致、原始增量与Nemotron正文一致，最大积压555.0ms；EOF保留尾词诊断。详见[报告](../reports/soulx/20261101-ntf007-teacher-append-only/README.md)。

| 单 | 工作单元 | 依赖 |
| --- | --- | --- |
| NTF-006 | 官方外层 `speak` 兜底与 `speech_detected` 门控的可见字段；本地完成，字段验收并入 NTF-008；配对器相关要求在 NTF-008 一并移除 | — |
| NTF-008 | 方案 A 单块音频缓冲，输入顺序严格为音频→文本→结束符；删除配对器与complete后整轮重识别，状态即时发布；本地完成，待远端预检 | 006、007 |
| NTF-009 | 固定 FDB30 同卡对照与延迟验收，不设分卡臂 | 008 |

NTF-005已完成并归档至本地`archive/`：双ASR独立计算与有界配对已交付，本地100项、预检3/3通过；正式18/30完整、12条触及800ms停止线，退出1，2134帧来源及配对审计通过。共同18条打断nonidle 4/6→6/6，但接话和主块口径停顿退化，状态未整体改善；完整样本EOF保留14个未配齐状态。见[正式报告](../../reports/soulx/20261031-dual-asr-publication/README.md)。11-01 10:12及收尾复查队列为空，不追加重跑，不切换下游Agent。

NTF-004已完成并归档至本地`archive/`：官方控制格式、门控和教师缓存修订已交付，本地30项、远端预检3/3通过；正式25/30完整、5条积压触限退出1。共同23条中停顿complete不变、打断nonidle 7/7→6/7，未见整体改善；EOF仍有待消费控制文字。见[对照报告](../../reports/soulx/20261031-nemotron-teacher-gate/README.md)。01:06:38 CST队列为空，未继续重试或切换现役Agent。

NTF-003 已完成并归档至本地 `archive/`：真实音频覆盖配对已修正，空增量规则保留；正式两轮25/30、28/30因800ms积压触限退出1，完整样本有部分改善但整体实时验收未通过，见[配对复测报告](../../reports/soulx/20261030-nemotron-teacher-alignment/README.md)。23:39远端队列为空，不继续重试或扩展规则修改。

NTF-001／002 已完成并归档至本地 `archive/`：教师文字前端与屏障已实现，本地20项检查、远端309帧预检及30/30条正式回放通过，3185帧执行顺序复查通过；此前没有验收两路音频进度配对。质量并未整体改善，见[报告](../../reports/soulx/20261030-nemotron-teacher-fdb30/README.md)。此前22:01服务器队列为空，当前状态执行前重查；未切换现役Agent或接入下游。

## 路线状态

| 路线 | 归档状态 | 入口 |
| --- | --- | --- |
| SoulX-Duplug | 当前活动：语音前端与 Shared Context 已实现，下游 LLM、思考与真实输出未接入 | [路线文档](../dev/SoulX-Duplug/README.md) |
| TextTurn | 已归档；共 11 项，7 项完成、TT-009 终止，TT-004／010／011 未完成 | [路线归档](../archive/dev/TextTurn/README.md) |
| VoxTurn | 已归档；仅完成现成权重与接入可行性调研，未部署 | [调研归档](../archive/dev/VoxTurn/research_assessment.md) |
| XTurnix | 已归档；XTX-001—005 与 XTX-007 完成，XTX-006 取消，XTX-009 仅完成来源审核 | [路线归档](../archive/dev/XTurnix/README.md) |

历史工作单不再维护进度，验收结论以归档文档和报告为准。TT-010 最后一次核查为 2026-10-27 12:47，r5 已冻结、pilot 未达质量线；该观察不表示作业仍在运行。XTX-008—013 草案已撤下，不恢复旧训练或已取消测试。

## 历史证据入口

| 内容 | 证据 |
| --- | --- |
| TextTurn 初始数据、模型与四类评测 | [数据冻结](../../reports/textturn/20261025-tt-001-freeze/README.md)、[训练](../../reports/textturn/20261025-tt-002-training/README.md)、[结果](../../reports/textturn/20261025-tt-004-results/README.md)、[v2 评分](../../reports/textturn/20261025-scoring-v2/README.md) |
| FDB 动作监控与 UltraChat 重测 | [480ms／160ms FDB 联合结果](../../reports/textturn/20261025-fdb-action-only/README.md)、[UltraChat 两周期结果](../../reports/textturn/20261025-ultrachat-prefix-retest/README.md) |
| TT-010 训练失败、修复与诊断 | [超时与续接停止](../../reports/textturn/20261026-tt-011-external-evaluation/README.md)、[放行／损失修复](../../reports/textturn/20261026-tt-010-loss-gate/README.md)、[动作平衡重训](../../reports/textturn/20261026-tt-010-balanced-training/README.md)、[四臂诊断](../../reports/textturn/20261026-training-diagnostics/README.md) |
| XTurnix FLEURS 与来源审核 | [FLEURS 报告](../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)、[48 会话审核](../archive/dev/XTurnix/source_audit.md) |

## 管理约定

工作单仅按用户明确指令建立；交付满足验收后立即归档并同步索引。历史停止、回退、失败和未完成记录保留在对应报告、归档区或 Git，不在入口反复追加已失效的运行快照。真实模型训练和集群测试使用远端 conda 调度作业，资源限制按相应工作单与已确认修订执行；实现同步维护 `docs` 下同路径中文说明。
