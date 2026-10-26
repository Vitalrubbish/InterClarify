# 工作单管理

2026-10-27用户明确要求依据已确认方案修复训练数据并启动训练。沿用TT-010，开始实施新版数据、输入映射、CPU规模预估和串行旧／新pilot验证；每臂最多5轮，不自动full或恢复TT-011。旧数据、旧报告和用户未提交修改保留。

2026-10-27 TT-010[完整修复配置](../dev/TextTurn/dataset_repair_recommendation.md)已整体确认，train／pilot窗口预算确定为100000／10000。按用户最新指令，本轮只更新为已确认，代码、正式JSON和旧冻结集未改动，数据构造、规模预估及训练未启动；TT-010保持打开，不新增issue或恢复外部评测。

2026-10-27按用户指令继续在TT-010内逐项核对修复配置，已确认发布时序参数及普通接话“句末点号弱标记＋首个合格空观察start”。采用弱代理是为自动构造，接受句末可能仍有续说，不用于冒充真实语音金标；[配置记录](../dev/TextTurn/dataset_repair_configuration.md)保留待定项。研究／架构合同已先同步，生成器、冻结集及训练尚未改动或启动，不新增issue。

2026-10-26 TextTurn四臂诊断已完成，均未得到可用设置，无活动作业。沿用TT-010交付[新方案](../dev/TextTurn/retraining_plan.md)：修复打断后重新接话及语义对照，更新内合并三类损失后统一裁剪，分开验证优化与数据收益。方案尚未实现或启动，确认集／full／外部测试均未执行；见[报告](../../reports/textturn/20261026-training-diagnostics/README.md)。

2026-10-26用户要求对TextTurn全keep做测试并确定新训练方案，沿用TT-010，不新增issue。r2训练已结束、两轮dev全keep且被gate拒绝；TT-011停止、未提交外部测试。只读复评作业已Running，后续串行pilot机制对照；见[诊断记录](../../reports/textturn/20261026-training-diagnostics/README.md)。

2026-10-26重训已启动并确认Running：`job-179298196307743501088-xuan-zhang`，10:32:46开始，run `tt-010-balanced-20261026-r2`，源码`b57b2ce`位于`source/tt010-balanced-r2`。用户授权取消训练时间上限：配置null、内外层训练timeout移除；1%正例门槛、三类等份损失及全部非时长资源限制保留。最近部署核查baseline-dev2501/88947；TT-011新等待器PID1400303、目录`dataset/tt-011-external-r2`，无等待截止，已连续轮询并核实存活，测试尚未提交。见[重训报告](../../reports/textturn/20261026-tt-010-balanced-training/README.md)。下方旧运行／时限状态为历史。

2026-10-26用户明确要求重新启动训练并取消训练任务时间上限：TT-010新run采用已交付的1%低门槛和三类等份损失，从固定基模重新训练，复用原完整数据。训练配置max_wall_seconds设为null，移除训练进程13800秒及外层14400秒timeout；训练仍按有限epoch自然结束。显存22GiB、单卡／8CPU／32GiB、资产10GiB／报告2GiB及30GiB空盘限制保留。TT-011按既有授权绑定新run重新部署等待，取消训练等待截止和等待器总时限，测试自身每项7200秒不变。不改动旧作业源码或产物，不新增issue。

2026-10-26放行／损失修复已交付：1%正例门槛、合格候选优先选模及最终full重验，阶段内三类有效损失各1/3；本地conda 62项回归、100818窗完整性及实际权重审核通过。历史全部keep候选已被新gate拒绝。未启动重训或外部测试，原时限问题保持记录；[修复报告](../../reports/textturn/20261026-tt-010-loss-gate/README.md)。

2026-10-26用户授权在TT-010内修复低门槛放行和损失平衡：接话／陈述／打断成功各至少1%，保留误动作约束；pilot／full独立将三类动作有效损失质量设为各1/3。先记录设计再实现，不新增issue或启动训练，TT-010／011保持未完成。

2026-10-26 09:38最新核查：TT-010训练02:14:21超时终止（退出码124、占卡13811秒）；pilot两轮88947窗均全部keep，full第1轮dev仅60001/88947窗，无正式候选及学习／重载验证。TT-011续接器02:14:38因训练失败停止，UltraChat与FDB均未提交，无新测试成绩；当前无活动作业。两单保持未完成，未重启训练／测试或改时限。见[结果核查](../../reports/textturn/20261026-tt-011-external-evaluation/README.md)。下方等待／运行状态为历史。

2026-10-26按用户指令启动TT-011：先核对训练并适配两条测试入口，冻结因果前缀审核，部署成功训练后的串行续接。两条兼容入口、审核和必要契约已交付；远端等待器已连续轮询并核实存活，00:25:56训练pilot第2轮dev14001/88947，尚未提交测试。见[运行记录](../../reports/textturn/20261026-tt-011-external-evaluation/README.md)。

2026-10-25按用户明确指令新增[TT-011](TextTurn/tt_011_post_training_external_evaluation.md)：先修复UltraChat正文注入与FDB真实录音两条外部回归管线，再部署等待TT-010训练成功并放行后的自动串行测试。当前仅建立工作单，尚未修复、部署续接或提交测试。TextTurn共11项：7项完成、1项终止归档、3项未完成；范围及启动条件以本单为准。

2026-10-25 TT-010完整轨迹修订已核查、远端训练已启动：train21来源9977窗，pilot1894窗，dev200来源88947窗，全部选中轨迹逐拍监督，keep组权重封顶、start/stop各2；47项回归及完整性核查通过。用户已明确授权直接启动远端训练并取消旧累计GPU剩余预算限制，仍保留单作业资源和质量门槛；TT-010重新打开，当前7项完成、1项终止归档、2项未完成。作业job-179293824747465991917-xuan-zhang已确认Running，22:24:10开始，当前开发集基线7001/88947，未宣称训练完成。见[训练报告](../../reports/textturn/20261025-tt-010-fulltraj-training/README.md)。以下为此前记录。

2026-10-25 TT-010新修订实施中：按用户要求完整轨迹逐拍监督，取消类别内keep删拍，使用正损失权重控制重复keep；维持10000训练快照上限，改按完整来源组选取。沿用TT-010，不新增issue；用户进一步授权核查通过后直接启动远端训练，取消旧累计GPU剩余预算限制，保留单作业资源上限。旧r2抽样交付保留为历史，不能作为新修订已完成证据。

2026-10-25 TT-010回退后重建交付：按用户最新授权选160ms，train160来源／9071快照、dev200来源／11272快照，陈述start各50%；句中停顿0.20随机插入1—5窗，用户附和逐Speak窗0.01随机插入，去用户末尾句读，歧义keep及finish专用ID保留。41项回归、全快照及六条生命周期诊断通过，[TT-010](TextTurn/tt_010_asr_update_yield_dataset.md)重新归档；未训练或提交GPU作业。见[报告](../../reports/textturn/20261025-tt-010-duplex160/README.md)。当前8项完成、1项终止归档、1项未完成（TT-004）。以下回退重开及旧状态为历史。

2026-10-25 TT-010回退重开：用户明确要求撤销旧实现，旧完成记录不再有效；新控制窗选择160ms，参考DuplexCascade构造随机用户附和及更频繁句中停顿，补齐陈述比例及用户末尾标点处理。保持歧义keep和专用finish，不训练或提交GPU作业。当前TextTurn共10项：7项完成、1项终止归档、2项未完成（TT-004、TT-010）。见[工作单](TextTurn/tt_010_asr_update_yield_dataset.md)。以下为历史记录。

2026-10-25归档：[TT-008](archive/TextTurn/tt_008_ultrachat_stop_retest.md)的480ms／160ms各150/150场景成功，作业退出码0，18:24:38结束，按用户指令归档。结果见[报告](../../reports/textturn/20261025-ultrachat-prefix-retest/README.md)。TextTurn共10项：7项完成、1项终止归档、2项未完成（TT-004、TT-010）；旧停止词覆盖不能替代TT-010的非附和更新让轮验收。下方启动及策略讨论保留为历史。

2026-10-25最新指令：[TT-009](archive/TextTurn/tt_009_conditional_data_rebuild.md)终止归档，未实施、不计完成；新增[TT-010](TextTurn/tt_010_asr_update_yield_dataset.md)，训练数据改为Speak下非backchannel式ASR更新即让轮、短附和keep，不等待固定停止词，同时论证播放结束后的外部finish标记与start终态配对。TT-008已按冻结配置完成并归档，未因新合同更改既有标签或评分。TextTurn共10项：7项完成、1项终止归档、2项未完成。仅建立新工作单，未启动数据构造或训练。

2026-10-25启动TT-008：用户授权推进到服务器测试提交并稳定运行。固定30个既有UltraChat test来源，复用干净文本及已保存的在线ASR时间戳事件，480ms／8 token与160ms／3 token串行执行；沿用原剩余预算，不启动TT-009。远端作业已提交并确认480ms首阶段稳定，160ms同作业自动接续，最终结果待交付。实施及调度证据见[TT-008](archive/TextTurn/tt_008_ultrachat_stop_retest.md)。

历史修订（TT-009条件已被上方新指令替代）：[TT-008](archive/TextTurn/tt_008_ultrachat_stop_retest.md)取消空／不可见assistant_visible配置，不做有／无正文对照；UltraChat固定候选的480ms、160ms测试均执行，分别每个控制周期注入8 token、3 token助手正文，使用同一来源清单，串行运行、分别报告。[TT-009](archive/TextTurn/tt_009_conditional_data_rebuild.md)仍仅在TT-008交付且用户明确判定效果不好并指令启动后重构训练数据。本次只更新工作单，未执行重测、重构或训练，TextTurn共6/9完成。正常结束仍是生命周期转Listen，stop专用于用户打断。两种配置共用既有剩余预算，不新分配GPU额度，不将结果写成已证明正文注入因果作用。

2026-10-25用户最新确认：在TT-004内按“连续Speak与在线ASR更新区间重叠实际时长>960ms”直接统计抢话，不要求补齐语义标注。只重评已有trace，不新建issue、重训或提交GPU作业；原按固定3周期的已归档结果保留为历史口径。同时核对训练角色标识及评测输入字段，区分角色标记与助手已生成正文前缀。

2026-10-25最终核查：TT-005／006的480ms及TT-007的160ms FDB测试均100/100、退出码0、无未知；逐例trace、原始资产、模型摘要与时间计算均核对通过，三项已归档，TextTurn共6/7完成。160ms更新后Speak46/50、start9/50，这9条平均等待303.45ms；更新前连续3周期Speak46/50。详见[联合结果](../../reports/textturn/20261025-fdb-action-only/README.md)。TT-004仍未完成；不把行为统计当完整能力通过。下方为启动及修复历史，以本段最终核查为准。

2026-10-25状态核查：480ms r4已100/100、退出码0。原160ms续接进程已退出，waiting记录失效；已保留原状态并按相同源码／候选／清单补交，调度`job-179291166384532199286-xuan-zhang`已确认Running。补交前累计19711秒、剩9089秒，本次上限7200秒。见[运行记录](../../reports/textturn/20261025-fdb-action-only/README.md)。

2026-10-25最新纠正：用户明确FDB只监控TextTurn，不需要模拟回答。TT-005／006及TT-007统一移除助手正文和生成／播放生命周期，状态仅由start／stop／keep驱动；旧480ms r3停止并保留撤回记录，修正后的480ms与160ms复用相同100条录音、候选和原累计预算，串行重提。修正后的480ms r4已运行，160ms续接器等待其结束后自动提交；详见[动作监控运行记录](../../reports/textturn/20261025-fdb-action-only/README.md)。

2026-10-25新增授权：用户要求新增[TT-007：160ms周期同样本FDB对照](archive/TextTurn/tt_007_fdb_160ms.md)，复用TT-005／006的100条录音、现有候选和原累计预算，原480ms作业继续运行。先更新研究范围中的周期实验例外，再实现参数化控制与评分；160ms测试串行排在480ms作业之后，当前尚未提交160msGPU作业。

2026-10-25 最新工作单：按用户要求修复 [TextTurn TT-004](TextTurn/tt_004_evaluation.md)评分器，再审计训练数据。当前TT-001—003共3项已归档；v2评分已在远端conda对原1200例trace及19994个文本窗口离线重评，不占GPU、不改候选。v2分离错误与未知，移除完整参考自动语义锚点；打断299/1、停顿298/2、附和173/127为正确/未知，接话600未知，整体证据不足，TT-004待语义标注覆盖后归档。数据审核发现时序捷径、固定模板和重复keep占比过高，给出构造及候选配比建议；冻结数据和训练未改动，不新建issue。详见[v2修复及数据审核](../../reports/textturn/20261025-scoring-v2/README.md)。

2026-10-25启动更新：用户已明确授权启动TT-005／006，已实现共用冻结、回放、评分和远端提交入口，本地6项边界测试通过；335候选中固定50＋50，Pause共62个标注区间。当前处于远端执行阶段，原始失败和修复记录保留，不提前归档、不宣称质量通过。详见[联合运行记录](../../reports/textturn/20261025-fdb-cross-dataset/README.md)。

2026-10-25最新补充：按用户明确要求，依据[两臂跨数据集计划](../dev/TextTurn/fdb_cross_dataset_plan.md)建立[TT-005：接话覆盖与延迟](archive/TextTurn/tt_005_fdb_turn_taking.md)及[TT-006：停顿介入率与归因](archive/TextTurn/tt_006_fdb_pause_handling.md)，分别交付50条真实录音结果，替代此前仅纳入TT-004的安排。必要抽样、适配和边界测试并入两项，不单设工程确认工作单；共用一次远端串行测试与原有预算。当前只有计划及工作单，没有冻结抽样、实现入口或提交作业。固定现有候选、真实ASR、Listen影子动作，FDB标注时序与当前语义策略分开报告；TT-004仍未完成，旧完整FDB作业不恢复。

2026-10-24 当前路线：用户已确认 **SoulX-Duplug＋Nemotron**，并要求简化为公开英文 Easy Turn 集上的质量与延迟测试；[方案](../dev/SoulX-Duplug/quality_test.md)已同步。本次只更新路线文档，未新建 issue、实现适配或启动远端作业。以下 XTurnix 内容保留为历史记录，不代表当前继续推进旧训练或恢复已取消测试。

2026-10-24 回滚说明：用户明确选择撤销全部阈值实验，恢复 `13ba980` 的工作单与实现记录；其后校准、ASR 时间控制、短延迟和训练入口草案已清理。以下为基点保留状态，不代表重新授权旧训练或取消的测试。当前仅执行[回滚清理](../dev/XTurnix/rollback_cleanup.md)，没有新建工作单。

更新：2026-10-23。

按用户明确指令，依据[Nemotron＋XTurnix 的 FLEURS 质量测试计划](../dev/XTurnix/quality_test_on_fleurs.md)，在 [XTurnix 工作单目录](XTurnix/README.md)推进 XTX-001—006。XTX-001 已完成输入与历史基线冻结并归档；XTX-002 已完成隔离环境、模型与协议冻结及 dev 验证并归档；XTX-003 已完成真实时钟回放器与模拟契约验证并归档；XTX-004 已完成离线评分入口与合成 trace 验证并归档；XTX-005 已完成 A10 远端作业入口与 5 条冒烟并归档；XTX-006 正式 100 条作业已按用户要求取消，随后完成 pause token 诊断，未产生正式成绩。

XTX-007 已完成[实际分析](../dev/XTurnix/training_feasibility_assessment.md)，用户同意先启动 40—60 个英文场景的来源与可判定性审核，[分析工作单](archive/XTurnix/xtx_007_training_feasibility.md)已归档。[XTX-009](XTurnix/xtx_009_training_data_freeze.md) 已交付[48 会话首轮审核](../dev/XTurnix/source_audit.md)：30 个条件候选、18 个歧义，当前可直接冻结的训练记录为 0。本次只放行来源审核，正式冻结仍依赖 XTX-008，约 200 场景双人试标、输入/环境、校准及训练均未启动；不切换现役控制路径。

| 工作单组 | 范围 | 进度 |
| --- | --- | --- |
| [XTurnix：FLEURS 两组件测试](XTurnix/README.md#fleurs-evaluation) | 固定输入与历史基线、组件协议、在线回放、独立评分、远端冒烟、100 条正式测试与报告 | 5/6 完成；XTX-006 正式作业已取消 |
| [XTurnix：可行性分析及条件性试训](XTurnix/README.md#vad-assisted-training) | 分析与讨论完成；已开展首轮来源审核，正式输入/数据及训练待条件 | 1/7；XTX-007 已归档，XTX-009 首轮审核完成、本项未完成 |

XTX-001 证据见[数据冻结报告](../../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)，XTX-002 证据见[协议冻结报告](../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)，XTX-003 证据见[回放器报告](../../reports/xturnix_fleurs/20261023-xtx-003-replay/README.md)，XTX-004 证据见[离线评分报告](../../reports/xturnix_fleurs/20261023-xtx-004-scoring/README.md)，XTX-005 证据见[A10 冒烟报告](../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)。依赖顺序及每项验收以组内入口和工作单为准。完成一项立即归档至 `docs/issue/archive/XTurnix/`，同步更新链接与状态；未实施不标记完成。真实模型测试仍需远端 conda、单作业及既定内存/磁盘上限。

此前 X2-Turn 实现和测试及其 X2Q 工作单已撤下，不因本轮工作单创建而恢复。历史记录可从 Git 与回退备份追溯。

研究范围与模块职责见[研究主文档](../research_design.md)，实施顺序与待定参数见[工程实施计划](../engineering_implementation.md)。XTX-007 完成的是分析与讨论，XTX-009 当前完成的是首轮来源审核，均不代表四类监督或训练通过。普通控制训练与影子验证继续作为条件性计划，不包含 CoT 条件化主动介入训练、Layer 0/1/2 训练、完整播放链集成或现役替换，也不恢复此前取消的测试。
