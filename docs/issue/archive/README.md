# 已完成工作单归档

本目录保留当前采用决定、正在运行的FDB任务所需修复，以及尚未进入Git历史的两份原始记录。旧执行任务、研究草稿修改和一次性清理记录统一在下表追溯；每个历史链接都已核对对应Git对象与删除前原文一致。历史命令、参数和未勾选项仅反映当时阶段。

## 当前直接入口

| 工作单 | 结论 |
| --- | --- |
| [047](047_tts_first_segment_latency.md) / [048](048_cross_request_kv_cache.md) | 用户接受300ms自然度取舍，采用300/1200ms与KV复用 |
| [051](051_kv_cache_generation_divergence.md) / [061](061_explicit_generation_policy.md) | BF16分歧原因；显式生成策略1.0，固定108对通过 |
| [062](062_adopt_streaming_latency_defaults.md) / [063](063_publish_xtalk_runtime.md) | 单一路线与X-Talk d6dc3bf发布 |
| [064](064_latency_report_and_backchannel_plan.md) | 分段延迟报告与后续首反馈优化方向 |
| [066](066_fdb_alignment_file_limit.md) / [067](067_defer_unavailable_fdb_judge.md) / [068](068_serialize_fdb_service_warmup.md) | FDB文件上限、GPT暂缓和独立预热 |
| [070](070_async_thinking_result_return.md) | 确认思考工具异步调用、结果回写 Layer 1；已同步研究草稿与图，具体协议继续讨论 |
| [071](071_independent_thinking_request_token.md) | 思考请求采用独立 special token，倾听和表达时均可调用；已同步静默调用图示，运行协议待实现 |
| [072](072_single_inflight_thinking_request.md) | 每会话最多一个思考请求在途，重复触发合并、不重启；已同步研究草稿与图，取消和更新机制待讨论 |
| [022回放边界](022_runtime_replay_boundary_ordering.md) / [041连接记录](041_local_remote_connection_documentation.md) | 原文尚无Git历史副本，本次保留并登记 |

完整FDB状态以[065](../065_full_fdb_two_axes.md)为准；归档不代表任务完成。当前研究范围见[研究草稿](../../research_idea.md)。

## 历史原文索引

| 已完成单元 | 固定历史原文 |
| --- | --- |
| Issue 001：冻结官方输入契约、基线与验收口径 | [001_input_contract_and_baseline.md](https://github.com/Vitalrubbish/InterClarify/blob/ffd17fe19d26efa92ac8a62fc11bdc2230111b4a/docs/issue/archive/001_input_contract_and_baseline.md) |
| Issue 001：官方 Word 输入远端验收任务单 | [001_remote_execution.md](https://github.com/Vitalrubbish/InterClarify/blob/ffd17fe19d26efa92ac8a62fc11bdc2230111b4a/docs/issue/archive/001_remote_execution.md) |
| Issue 001a：远端只读资产扫描 | [001a_asset_inventory.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/001a_asset_inventory.md) |
| Issue 001b：按官方 Word 输入对照控制路径 | [001b_runtime_comparison.md](https://github.com/Vitalrubbish/InterClarify/blob/ffd17fe19d26efa92ac8a62fc11bdc2230111b4a/docs/issue/archive/001b_runtime_comparison.md) |
| Issue 001c：修复重复接话拦截造成的历史分歧 | [001c_runtime_history_preservation.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/001c_runtime_history_preservation.md) |
| Issue 001d：降低完整 checkpoint 恢复的主存压力 | [001d_checkpoint_load_memory.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/001d_checkpoint_load_memory.md) |
| Issue 001e：修复输入校验反复计算词表大小导致掉拍 | [001e_prompt_validation_overhead.md](https://github.com/Vitalrubbish/InterClarify/blob/ad4b28ee3dd4da70c5d7ec0fe02fc641ab19866a/docs/issue/archive/001e_prompt_validation_overhead.md) |
| Issue 002/003 组件接入远端任务单 | [002_003_remote_execution.md](https://github.com/Vitalrubbish/InterClarify/blob/8235dc68ed9b22dd584ea96eda66c91c4b59cb80/docs/issue/archive/002_003_remote_execution.md) |
| Issue 002：接入 Nemotron EN 160ms 并采集真实轨迹 | [002_nemotron_streaming_integration.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/002_nemotron_streaming_integration.md) |
| Issue 002a：修复预热 WAV 容器格式读取 | [002a_warmup_wav_format.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/002a_warmup_wav_format.md) |
| Issue 003：接入 Kokoro 分段合成与唯一播放链路 | [003_kokoro_playback_integration.md](https://github.com/Vitalrubbish/InterClarify/blob/8235dc68ed9b22dd584ea96eda66c91c4b59cb80/docs/issue/archive/003_kokoro_playback_integration.md) |
| Issue 003a：修复 Kokoro 0.9.4 本地音色加载 | [003a_local_voice_loading.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/003a_local_voice_loading.md) |
| Issue 003b：缩短段时保留真实增量的词边界等待预算 | [003b_segment_word_boundaries.md](https://github.com/Vitalrubbish/InterClarify/blob/fd1354ed59d28402f7a8ac69de1b3be151cecbc5/docs/issue/archive/003b_segment_word_boundaries.md) |
| Issue 003c：Kokoro 分段试听复核 | [003c_audio_listening_review.md](https://github.com/Vitalrubbish/InterClarify/blob/8235dc68ed9b22dd584ea96eda66c91c4b59cb80/docs/issue/archive/003c_audio_listening_review.md) |
| Issue 003d：修复 Kokoro 句内分段不连续 | [003d_segment_continuity.md](https://github.com/Vitalrubbish/InterClarify/blob/8235dc68ed9b22dd584ea96eda66c91c4b59cb80/docs/issue/archive/003d_segment_continuity.md) |
| Issue 004 远端数据执行任务单 | [004_remote_data_execution.md](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eeae48deaa228ee00e359549d997aafd28f2/docs/issue/archive/004_remote_data_execution.md) |
| Issue 004：UltraChat micro-turn 数据生成与交付 | [004_training_data_and_annotation.md](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eeae48deaa228ee00e359549d997aafd28f2/docs/issue/archive/004_training_data_and_annotation.md) |
| Issue 004a：恢复中断的 UltraChat 来源获取 | [004a_source_download_recovery.md](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eeae48deaa228ee00e359549d997aafd28f2/docs/issue/archive/004a_source_download_recovery.md) |
| Issue 005：恢复训练状态并完成远端资源短跑 | [005_training_runtime_and_resource_probe.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/005_training_runtime_and_resource_probe.md) |
| Issue 006：执行三组有限话轮控制适配 | [006_punctuation_robust_adaptation.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/006_punctuation_robust_adaptation.md) |
| Issue 007：生成四配置FDB小子集能力报告 | [007_turn_control_evaluation.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/007_turn_control_evaluation.md) |
| Issue 008：真实音频、FDB v1.0 与英文底座冻结 | [008_full_chain_fdb_acceptance.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/008_full_chain_fdb_acceptance.md) |
| Issue 008a：当前英文完整链路官方权重接话复核 | [008a_official_full_chain_smoke.md](https://github.com/Vitalrubbish/InterClarify/blob/964424e2500774e796e22f30a368b475071eb14c/docs/issue/archive/008a_official_full_chain_smoke.md) |
| Issue 009：核对 issue 实际进度并维护归档 | [009_issue_progress_audit.md](https://github.com/Vitalrubbish/InterClarify/blob/c2f1b800aa13679cfce73ddc706843f259289e00/docs/issue/archive/009_issue_progress_audit.md) |
| Issue 022：主动插话研究 idea 草稿 | [022_research_idea_draft.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/022_research_idea_draft.md) |
| Issue 023：替换主动插话研究场景 | [023_research_scenario_revision.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/023_research_scenario_revision.md) |
| Issue 032：分析T1损失与类别加权依据 | [032_layer1_t1_loss_analysis.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/032_layer1_t1_loss_analysis.md) |
| Issue 033：核验训练产物并启动四配置FDB测试 | [033_layer1_fdb_test_launch.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/033_layer1_fdb_test_launch.md) |
| Issue 034：持续等待与FDB转写质量诊断 | [034_layer1_waiting_asr_diagnosis.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/034_layer1_waiting_asr_diagnosis.md) |
| Issue 035：编写正式 ASR 技术选型报告 | [035_asr_selection_report.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/035_asr_selection_report.md) |
| Issue 035：重核首轮训练与官方训练差异 | [035_official_training_comparison.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/035_official_training_comparison.md) |
| Issue 036：实现下一轮训练配置的论文对齐 | [036_layer1_paper_alignment.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/036_layer1_paper_alignment.md) |
| Issue 036a：删除更新参数范围的对齐目标 | [036a_remove_parameter_alignment.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/036a_remove_parameter_alignment.md) |
| Issue 037：按对齐配置重训并重测T2 | [037_layer1_t2_retraining_retest.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/037_layer1_t2_retraining_retest.md) |
| Issue 038：正式 TTS 选型报告与旧决策文档清理 | [038_tts_selection_report.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/038_tts_selection_report.md) |
| Issue 039：移除 ASR 正式报告中的首文本指标 | [039_remove_asr_first_text_metric.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/039_remove_asr_first_text_metric.md) |
| Issue 040：将回答启动统一移至下一静音拍 | [040_layer1_delayed_response_start.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/040_layer1_delayed_response_start.md) |
| Issue 040a：实现回答启动数据后移 | [040a_delayed_response_data.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/040a_delayed_response_data.md) |
| Issue 040b：最新延后启动数据全量加权训练 | [040b_delayed_start_full_training.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/040b_delayed_start_full_training.md) |
| Issue 040c：延后启动最终候选 FDB 测试 | [040c_delayed_start_fdb_test.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/040c_delayed_start_fdb_test.md) |
| Issue 043：撤销最近两次仓库清理提交 | [043_revert_cleanup_commits.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/043_revert_cleanup_commits.md) |
| Issue 044：仓库瘦身——旧路线实现、开关与过时文档引用 | [044_repository_slimdown.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/044_repository_slimdown.md) |
| Issue 045：删除 reports 下旧路线证据 | [045_remove_retired_route_reports.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/045_remove_retired_route_reports.md) |
| Issue 046：精简 reports/layer1_training | [046_minimize_layer1_reports.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/046_minimize_layer1_reports.md) |
| Issue 049：延迟优化对照与分段时延验证 | [049_latency_decomposition_validation.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/049_latency_decomposition_validation.md) |
| Issue 049：删除旧训练/FDB 设计及开关 | [049_remove_legacy_training_switches.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/049_remove_legacy_training_switches.md) |
| Issue 050：确认剩余表达时长的学习方式 | [050_implicit_duration_learning.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/050_implicit_duration_learning.md) |
| Issue 050：恢复远端延迟测试依赖并重提任务 | [050_restore_latency_test_dependencies.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/050_restore_latency_test_dependencies.md) |
| Issue 051：确认独立思考模块与按需唤醒方向 | [051_thinking_module_architecture.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/051_thinking_module_architecture.md) |
| Issue 052：整理系统架构讨论与思考模块路线 | [052_research_discussion_consolidation.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/052_research_discussion_consolidation.md) |
| Issue 053：将工程方向移至研究草稿后部 | [053_research_document_structure.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/053_research_document_structure.md) |
| Issue 054：明确研究前提与核心目标 | [054_research_contribution_focus.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/054_research_contribution_focus.md) |
| Issue 055：排除大型延迟诊断原始结果 | [055_ignore_raw_latency_evidence.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/055_ignore_raw_latency_evidence.md) |
| Issue 056：确认人类感知评价的阶段范围 | [056_human_perception_evaluation.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/056_human_perception_evaluation.md) |
| Issue 057：交付300ms首段音频供自然度复评 | [057_audio_review_delivery.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/057_audio_review_delivery.md) |
| Issue 058：收敛首阶段主动澄清范围 | [058_clarification_research_scope.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/058_clarification_research_scope.md) |
| Issue 059：确认自主澄清任务并结束本轮问题整理 | [059_autonomous_clarification_scope.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/059_autonomous_clarification_scope.md) |
| Issue 060：同步用户文档清理 | [060_document_cleanup_sync.md](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/060_document_cleanup_sync.md) |

本次移出工作树58份旧归档，原文通过固定提交追溯；远端原始结果保持。清理与核验见[069](069_archive_document_cleanup.md)。
