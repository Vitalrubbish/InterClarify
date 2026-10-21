# 开发与测试 issue 索引

## 当前工作

| 编号 | 工作单元 | 状态与范围 |
| --- | --- | --- |
| [047](047_tts_first_segment_latency.md) | 首段 TTS 聚合期限降至 300ms | 进行中；后续段保持 1,200ms、micro-turn 保持 600ms，比较延迟、连续性与听感 |
| [048](048_cross_request_kv_cache.md) | 跨 micro-turn 请求复用 KV cache | 进行中；按会话复用匹配前缀，验证正确性、时延与显存，不改变拍长或重启训练 |

两项已实现并完成本地回归，[049 延迟对照](archive/049_latency_decomposition_validation.md)已提交远端任务 `job-179251495575111326759-xuan-zhang`，已完成，结果见[分段报告](../../reports/latency/20261021-r2/results.md)。047待人工复听，051已查明BF16分段计算与重复惩罚造成近并列排名翻转，048继续正式采用验收。

[035 ASR 正式选型报告](archive/035_asr_selection_report.md)已完成归档；报告汇总 2026-10-16 测量及后续输入复核，见 [正式报告](../asr_selection_report.md)。

[038 TTS 正式选型报告与旧决策文档清理](archive/038_tts_selection_report.md)已完成归档；见 [TTS 报告](../tts_selection_report.md)。两份旧 decision 文档已由正式报告取代，当前链接已迁移。

[039 ASR 首文本指标移除](archive/039_remove_asr_first_text_metric.md)已完成归档；按用户要求移除正式报告中的该列及相关表述，保留原始测量证据。

更新：2026-10-20。目标组合为 **Nemotron EN 0.6B/160ms + Kokoro 82M/af_heart**。首轮四配置、第二轮T2及第三轮延后启动T2的固定FDB子集实验已交付。用户明确接受当前话轮控制误差，停止继续训练；006、007、008、037、040、040c已关闭归档。完整FDB、官方评分及全面人工音频复核未执行，不冒充通过。正式结果见[Layer 1训练与FDB阶段报告（历史版本）](https://github.com/Vitalrubbish/InterClarify/blob/717fcf037d471d07be41172b5b69b0dd404cfcb6/docs/layer1_training_fdb_report.md)。

| 编号 | 任务 | 当前状态与剩余工作 |
| --- | --- | --- |
| [001](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001_input_contract_and_baseline.md) | 官方输入契约与基线 | 完成，已归档；五例共 136 拍一致，资产及生命周期证据齐全 |
| [001b](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001b_runtime_comparison.md) | 官方控制路径对照 | 完成，已归档；原生 Word 输入、五例真权重和远端 7 项测试通过 |
| [002](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/002_nemotron_streaming_integration.md) | Nemotron 在线接入 | 完成，已归档；r4-asr 退出 0 |
| [003](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/003_kokoro_playback_integration.md) | Kokoro 分段播放 | 完成，已归档；[003d修复](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/003d_segment_continuity.md)及[003c用户复听](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/003c_audio_listening_review.md)通过 |
| [004](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/004_training_data_and_annotation.md) | UltraChat micro-turn 数据管线 | 完成归档；r5全量机器审计通过，用户明确免除复审后关闭 |
| [005](archive/005_training_runtime_and_resource_probe.md) | 训练恢复与资源短跑 | 完成归档；024真实恢复精确一致，025资源测量完成；当时保守选择512，现006按用户要求改为2048 |
| 017 | 完整训练加载与零更新 | 完成、已归档；零更新通过，回归拍界抖动由用户明确接受；过程报告已按精简要求删除 |
| [006](archive/006_punctuation_robust_adaptation.md) | 四配置基线与三组有限适配 | 完成，已归档；三轮有限训练和最终候选交付，用户决定停止继续训练 |
| [007](archive/007_turn_control_evaluation.md) | 四配置FDB小子集能力报告 | 完成，已归档；四配置及后续两轮T2的阶段能力报告交付 |
| [008](archive/008_full_chain_fdb_acceptance.md) | 真实音频与 FDB 执行/验收 | 完成，按当前阶段范围归档；固定子集执行交付，完整FDB/官方评分未执行 |
| [036](archive/036_layer1_paper_alignment.md) | 论文配置对齐实现 | 完成归档；类别加权及10% warmup，保持2e-5及已有LoRA；用户豁免开训前短跑 |
| [037](archive/037_layer1_t2_retraining_retest.md) | T2重训与重测 | 完成，已归档；第二轮训练与25会话结果保留作对照 |
| [040](archive/040_layer1_delayed_response_start.md) | 回答启动后移一拍 | 完成，已归档；新数据、全量加权训练及25会话重测交付，用户接受当前误差 |

远端执行见 [001 任务单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001_remote_execution.md)与 [002/003 任务单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/002_003_remote_execution.md)。001 只验证一套官方配置：Kyutai Word 逐词 strip、每拍空格连接、首非空 Word 起拍、600ms、BF16、64-token 贪心。raw 字符增量和 160ms 超时释放残词均不等同官方 Word；不展开时钟、发布粒度与句读矩阵。旧 raw/超时残词报告只作诊断；新原生 Word 五例全部通过，结果见 [001 验收报告](../../reports/layer1_training/issue001-word-20261019/README.md)。

[008a 官方权重完整链路诊断](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/008a_official_full_chain_smoke.md)已完成：当前五例新正文/语音0/5，共178拍无协议/组件错误。后续有限训练及固定FDB子集实验均已交付，当前按用户接受范围收口。

## 依赖与交付

004工具实现[013](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/013_layer1_data_pipeline_implementation.md)、[来源恢复](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/004a_source_download_recovery.md)与[016来源隔离](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/016_external_data_exclusion.md)已完成归档；用户取消FDB补转写及其训练前置条件。[完整数据任务](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/004_remote_data_execution.md)已完成，与017加载/零更新分别跟踪数据及权重证据，不能把代码或来源验真当正式训练放行。

[018正式数据交付](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/018_layer1_data_delivery.md)按用户决定先有限抽取最多6000原始对话再过滤/去重/切分。r3监督冲突由[019](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/019_duplex_data_alignment_audit.md)修复，旧产物已删除；r5在调试机1CPU/nice10/2GiB硬限完成，正式切分、32/100子集、机器审计及用户免除复审的记录见[r5报告](../../reports/layer1_training/issue004-build-20261019-r5/README.md)。

[020文本表面形式核查](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/020_asr_text_surface_alignment.md)完成了用户审阅r4后的补充核验；[021修订](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/021_asr_surface_data_revision.md)交付r5。用户明确免除r5新增人工复审，004已按机器证据及该授权关闭。

[015 调试机资源实测](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/015_debug_node_data_validation.md)完成：32条诊断在1CPU下约6.9秒、峰值约150MiB；同规模轻量检查直接在调试机受限执行。r4测试/诊断及完整来源下载最终均通过退出0。

本阶段001/004/005前置、006训练资产、008固定子集执行及007能力报告均已交付并归档；最终交付为T2_R3_delayed_start。后续完整FDB或其他层研究需另行立项，不因本阶段残余误差继续训练。

| 已确定路线 | 必须交付的证据 | 主责 |
| --- | --- | --- |
| 使用论文采用的 UltraChat | 实际 revision/split/许可、原始 ID 与摘要、1,000/200/300 切分；精确作者 50k 清单未知时如实记录 | 001、004 |
| 自行实现 micro-turn 生成 | 论文参数映射、事件/监督/句读混合、固定种子审计与测试 | 004 |
| 从官方 checkpoint 继续训练 | 完整恢复、零更新对齐、仅已有 q/v LoRA 更新、训练状态恢复与可重载资产 | 005、006 |

## 共用约束

- 遵循[研究 idea](../research_idea.md)与[当前 issue 索引](README.md)。状态使用待办、进行中、阻塞、完成，完成时记录提交、run_id、结果路径和遗留问题。
- 修改现有文档时直接维护当前版本；实验过程和失败保留在报告，避免重复追加互相更正的计划。实现优先修改现有模块，代码与同路径中文说明同步，文件名、注释和提交消息使用英文。
- 本地和远端使用 conda；真实模型及集群测试在远端调度作业执行，冻结两仓库源码、资产、数据、种子、时钟和预算，独立 run_id，保留失败及退出码。
- 保持五类控制 token、完整生成历史、唯一协议执行/仲裁路径与唯一播放所有权；已播放内容不可撤销，Layer 3 仅能修订未提交片段。
- 001/004/007 在候选结果前冻结数据和评价门槛；005 实测冻结训练配置。不得用 test/FDB 调参，不以成功样本均值掩盖漏答。音频目标均值约 1s、上限 1.5s，简单问题亚秒，008 补齐实际停播与 FDB 门槛。

## 归档

[060 文档清理同步](archive/060_document_cleanup_sync.md)已完成归档：保留用户删除的文档与评测章节，相关追溯引用改为固定历史版本，并同步研究草稿章节编号。

[059 自主澄清任务确认](archive/059_autonomous_clarification_scope.md)已完成归档：模型自主发现信息缺口、确定澄清目标与介入决策；删除研究草稿的未决问题整节，调整章节编号并结束本轮提问。

[058 主动澄清研究范围](archive/058_clarification_research_scope.md)已完成归档：首阶段聚焦询问缺失信息，主动纠错与其他任务引导留作后续扩展。

[056 人类感知评价范围](archive/056_human_perception_evaluation.md)已完成归档：首阶段采用旁听感知实验，真人交互及组合方案保留为时间允许时的扩展，明确感知结论的适用范围。

[054 研究贡献定位](archive/054_research_contribution_focus.md)已完成归档：明确主动插话价值为需证据支撑的前提，在线介入判断为核心研究目标，架构服务于该目标。

[053 研究草稿结构调整](archive/053_research_document_structure.md)已完成归档：将系统架构与工程实现方向移至研究草稿文末第 9 节，更新交叉引用，保留研究方法及已有方案。

[052 研究架构讨论整理](archive/052_research_discussion_consolidation.md)已完成归档：研究草稿汇总今日共识，思考模块倾向先提示词原型再专项训练，同时保留仅提示词与直接训练方案；更新架构未决问题，未修改实现。

[051 独立思考模块架构](archive/051_thinking_module_architecture.md)已完成归档：记录思考模块提交介入意图、保留完整问句方案，以及表达模块通过 special token 按需唤醒的方向；仅更新研究草稿，未修改运行协议或模型。

[050 剩余表达时长隐式学习](archive/050_implicit_duration_learning.md)已完成归档：研究草稿记录隐式学习与混合线索数据方向；仅确认研究设计选择，未实现数据或启动训练，时长是否为必要条件仍待讨论。

[036a删除参数范围对齐目标](archive/036a_remove_parameter_alignment.md)完成：036/037保持仅训练已有q/v LoRA，embedding/head冻结；未修改运行配置。

[035训练模式重核](archive/035_official_training_comparison.md)完成：见[完整对照（历史版本）](https://github.com/Vitalrubbish/InterClarify/blob/717fcf037d471d07be41172b5b69b0dd404cfcb6/docs/layer1_training_comparison.md)，区分论文加权声明与公开推理包装器普通CE，列出除上下文长度外的已确认差异和未公开项。未修改首轮配置或启动新训练。

[026 单卡2048持续训练检查（历史版本）](https://github.com/Vitalrubbish/InterClarify/blob/717fcf037d471d07be41172b5b69b0dd404cfcb6/docs/issue/archive/026_layer1_2048_stability.md)完成：100步/200序列未OOM，实际曝光95条对话，显存分配峰值20.262GiB；详见[报告](../../reports/layer1_training/issue026-2048-20261020/README.md)。029据此切换正式窗口和索引；030按用户路线移除dev评测器开训要求。

[023 研究场景修订](archive/023_research_scenario_revision.md)已完成：以复试通知适用性和打印机诊断替换 [idea 草稿](../research_idea.md)的人员排班示例，保留共同前缀、续说分支及收益/负面影响评级；测量场景仅作扩展示例。

[022 主动插话研究 idea 草稿](archive/022_research_idea_draft.md)已完成：见 [research_idea.md](../research_idea.md)，整理统一在线决策、共同前缀六分支，以及信息收益与插话负面影响的高/中/低分析。仅交付讨论草稿，不改变现有实现或启动训练。

已有完成实现：[001a 资产扫描](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001a_asset_inventory.md)、[001c 历史保持](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001c_runtime_history_preservation.md)、[001d 加载压力](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001d_checkpoint_load_memory.md)、[001e 校验耗时](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001e_prompt_validation_overhead.md)、[002 接入](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/002_nemotron_streaming_integration.md)、[002a WAV 读取](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/002a_warmup_wav_format.md)、[003a 音色加载](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/003a_local_voice_loading.md)、[003b 分段计时](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/003b_segment_word_boundaries.md)。

文档维护：[009 进度核对](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/009_issue_progress_audit.md)、[010 官方输入核实与计划收敛](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/010_issue001_scope_reduction.md)。001/001b 和远端任务单现已基于新证据完成归档；训练仍受 004/005 等前置约束，保持 false。

远端维护：[011 清理无用环境与目录](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/011_remote_storage_cleanup.md)完成并归档。Qwen3-ASR模型/专用环境及旧ASR/TTS选型开发实现已删除，原始结果和现役资产保留；主清单约6.25GiB目标占用已清理。

[012 主目录归拢](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/012_remote_home_consolidation.md)已完成：24个历史目录归入interclarify-archive，顶层目录50→26；当前路径按[远端目录约定](../remote_workspace.md)和迁移清单查找。

[014 实际缓存/退役资产回收](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/014_remote_cache_reclamation.md)已完成：直接删除14个编译缓存、3组候选权重、2套旧环境，目标删除前占用约20.58GiB；当前模型、训练环境和原始结果保留。

[020核验](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/020_asr_text_surface_alignment.md)已完成：调试节点单GPU可运行该短探针，现役ASR保留大小写/缩写并主要输出英文数词；[021](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/021_asr_surface_data_revision.md)已完成用户数值口语化及r5审计，r4已删除，004按用户授权关闭。

[040a回答启动数据后移](archive/040a_delayed_response_data.md)已完成归档；代码、配置、审计与同路径文档同步，32项本地/远端数据测试通过，实际重建和审计退出0，见[数据交付](../../reports/layer1_training/issue040-delayed-start-data-20261020/README.md)。

[040b全量加权训练](archive/040b_delayed_start_full_training.md)按用户直接训练授权执行独立第三轮，作业`job-179250231441693568614-xuan-zhang`，最新数据1000条T2/1235步，详见[启动记录](../../reports/layer1_training/issue040-delayed-training-20261020/README.md)。

[043撤销最近两次清理提交](archive/043_revert_cleanup_commits.md)已完成归档：用反向提交恢复旧训练探针及X2/MOSS/TurnSense组件，未触碰正在运行的训练作业，保留原有未提交改动。

[044仓库瘦身](archive/044_repository_slimdown.md)已完成归档：经用户重新确认，删除X2/MOSS/TurnSense/round1-A4旧组件栈、issue005探针训练路线、`--native`对照开关及已归档任务的一次性工具，并清理文档悬空引用。保留当前FDB驱动、`xtalk_link_check.py`、T1/T2/T3参考条件和延迟启动数据协议。

[040c延后启动候选测试](archive/040c_delayed_start_fdb_test.md)已完成归档；25/25会话执行成功，退出0，自然接话新回复3/5、合成插话后新回复5/5。用户要求结束当前阶段并停止继续训练，已知限制及未执行项保留在正式报告。

[045删除reports旧路线证据](archive/045_remove_retired_route_reports.md)已完成归档：删除issue005 probe-only报告目录，512索引仅保留为`tests/fixtures`回归基线；维护记录按用户确认保留。

[046精简Layer1报告](archive/046_minimize_layer1_reports.md)已完成归档：`reports/layer1_training`只保留配置/测试直接依赖与正式报告引用证据，由约9.6MiB降至约1.5MiB。

[049删除旧训练设计](archive/049_remove_legacy_training_switches.md)已完成归档：只保留T2_R3最终路线，删除036探针、旧时序兼容、006/037条件、FDB旧模式及三个离线分析脚本。

[049 延迟分解对照测试](archive/049_latency_decomposition_validation.md)已完成归档：实现047/048后，按原始基线、仅300ms、300ms加KV cache三组串行重测固定25会话，并交付整体与分段延迟。用户已授权执行，不重启训练。

[050 远端测试依赖恢复与重提](archive/050_restore_latency_test_dependencies.md)已完成归档：r1快照完整，已恢复误删的现役训练资产清单并以独立r2重提原测试；保留旧任务证据。

[051 缓存生成分歧排查](archive/051_kv_cache_generation_divergence.md)完成归档：确认BF16分段数值差异与重复惩罚后的近并列排名翻转；位置/mask/前缀核对通过。048继续负责正式采用及更广在线行为验收。

[055 原始延迟证据忽略规则](archive/055_ignore_raw_latency_evidence.md)已完成归档：完整诊断JSON保留本地/远端，Git提交关键摘要及追溯哈希，减少本轮提交体积。

[057 自然度复评音频交付](archive/057_audio_review_delivery.md)完成归档：300/600ms各5条原始组件WAV已取回并校验，试听包不入Git；047等待用户复听反馈。

[061 显式线上生成策略](archive/061_explicit_generation_policy.md)完成归档：统一greedy/单beam/repetition_penalty=1.0，health/响应自动核对规则；远端108/108对固定请求一致，主源码已同步。
