# 工作单管理

更新：2026-11-02。用户已确认 **SoulX原生控制＋独立原生流式转写**，并要求建立相关工作单。新方案保留SenseVoice内部教师链路，Nemotron仅供共享正文，两路各自就绪即发布，不等待逐块配齐。设计见[独立流式前端](../dev/SoulX-Duplug/independent_streaming_frontend.md)、[研究方案](../research_design.md)与[工程计划](../engineering_implementation.md)。

## 当前工作单

| 工作单 | 工作单元 | 依赖 | 状态 |
| --- | --- | --- | --- |
| [NTF-015](NTF-015.md) | 保留原生协议的SoulX控制封装及reset审计 | 无 | 待实施 |
| [NTF-016](NTF-016.md) | 同源音频分发与独立Nemotron流式正文 | NTF-015输入合同 | 待实施 |
| [NTF-017](NTF-017.md) | 正文／状态独立更新、原子快照与生命周期 | NTF-015／016 | 待实施 |
| [NTF-018](NTF-018.md) | 完整预热、远端积压归因及实时门槛 | NTF-015—017 | 待实施 |
| [NTF-019](NTF-019.md) | 固定FDB30单路／双路验收 | NTF-018通过 | 待实施 |

本轮只设计与建单，尚未实施或提交远端作业。预热不足作为优先验证假设，分别对照既有有限预热与完整预热，区分首遇路径长尾和持续吞吐问题；不预先归因全部积压。远端单并发、1×4090、4CPU、32GiB、显存22GiB停止线，保留800ms过载保护，具体预算见各工作单。下游Agent尚未切换，不训练、不接LLM／CoT／TTS，也不恢复旧comparison入口。

## 已归档实验

NTF-011／012已完成，NTF-013离线归因和NTF-014源码重置也已完成并归档。comparison旧实验已清除，官方源码已重新克隆并显式纳入子模块，见[清理报告](../reports/soulx/20261102-source-reset/README.md)。旧教师替换、配对发布仅保留历史证据。

[NTF-011](../reports/soulx/20261101-ntf011-x2-probe/README.md)单进程门槛通过；[NTF-012](../reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)同卡FDB30完成30/30、退出0，主块发布P95 152.8ms、显存14046MiB、3185帧规范分词全通过、尾词退化追加0。20条在线WER为10.06%（r6为10.90%），但状态未整体改善，见[归因](../reports/soulx/20261101-ntf012-x2-teacher-fdb30/regression_analysis.md)。

TextTurn、VoxTurn、XTurnix按用户指令归档，文档见[归档区](../archive/dev/README.md)，实现见[archive](../../archive/README.md)，历史工作单保留在本地`docs/issue/archive/`，不进入Git。

NTF-010 已收口：词级规范分词保留，`r6` 固定30条 30/30完整、退出0、主块P50/P95 208.5/219.6ms、最大405.3ms、无800ms触发、`buffer_overflow=0`，但“一个空ASR增量即提交尾词”产生`post_pause_extension=17`（13条用例），两次停顿版本为4次。该判据被证伪；X2 官方EOS闭合发射组取代它（执行前源码核查修订），不再使用空步启发式。

NTF-001—009 均已完成并归档；NTF-009 固定30条同卡对照 30/30完整、退出0、主块P95 219.2ms、无800ms触发，状态指标混合改善。

NTF-009 已完成并归档至本地 `archive/`：固定FDB30同卡、源码`4568ecf`、run `ntf009-teacher-fdb30-20261101-r1`。预热按合同执行；30/30完整、退出0，最大主块积压663.8ms，主块发布P50/P95 205.9/219.2ms，完整观察P95 120.2ms；`buffer_overflow=0`，30条EOF部分块逐例记录，complete无重识别。同25条中接话提前complete 6/9→5/9、>160ms提前6/9→4/9，打断结束后complete 2/9→4/9；停顿区间内complete 2/7→0/7，其中ID127在区间起点前40ms。详见[报告](../reports/soulx/20261101-ntf009-teacher-fdb30/README.md)。

NTF-008 已完成并归档至本地 `archive/`：音频embedding有界缓冲、首块不特判、配对器删除、complete不重识别，三轴预检3/3、退出0；首轮`r1`批量步骤失败已保留并在`4c81904`修复。详见[报告](../reports/soulx/20261101-ntf008-teacher-buffer/README.md)。

NTF-007 已完成并归档至本地 `archive/`：删除教师文本门控、`_revise()`、KV检查点、输入账本和三项缓存上限，改为增量追加与尾部重编码审计。远端 `ntf007-teacher-smoke-20261101-r1` 三轴预检3/3、退出0，逐帧确认控制文字前缀追加、token累计一致、原始增量与Nemotron正文一致，最大积压555.0ms；EOF保留尾词诊断。详见[报告](../reports/soulx/20261101-ntf007-teacher-append-only/README.md)。

NTF-006 已完成并归档至本地 `archive/`：`service_state`、`service_completion_source`、`speech_detected`、`service_text`与`no_speech`门控在NTF-008教师帧中发布并验证；`wait_fallback`属于已归档的SenseVoice外层，现役路径不产生。

| 单 | 工作单元 | 状态 |
| --- | --- | --- |
| NTF-001—006 | 教师文字前端、门控、配对与官方服务字段 | 已完成并归档 |
| NTF-007 | append-only 教师文本 | 已完成并归档 |
| NTF-008 | 音频embedding缓冲、即时发布、无complete重识别 | 已完成并归档 |
| NTF-009 | 固定FDB30同卡对照与延迟验收 | 已完成并归档 |
| NTF-010 | 词级规范分词教师文本追加与FDB30复测 | 已收口，尾词空步判据被证伪 |
| NTF-011 | X2 单帧流式可行性门槛 | 已完成并归档；r2四条通过，退出0 |
| NTF-012 | X2 EOS闭合发射组适配与固定FDB30对照 | 已完成并归档；30/30、实时与规范性通过，状态混合 |
| NTF-013 | 状态退化离线归因 | 已完成并归档；时序／规则耦合，语义对齐仍待验证 |
| NTF-014 | 清除comparison实验、显式引入官方源码 | 已完成并归档；60项删除，本地／远端官方checkout一致 |

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
