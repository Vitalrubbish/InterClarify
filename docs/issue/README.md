# 开发与测试 issue 索引

更新：2026-10-19。目标组合为 **Nemotron EN 0.6B/160ms + Kokoro 82M/af_heart**，001 官方控制对照已通过，继续准备有限 Layer 1 训练，尚未开训。这里是仓库内任务单；完成任务移入 `archive/`，父任务仅在全部条件满足后归档。

| 编号 | 任务 | 当前状态与剩余工作 |
| --- | --- | --- |
| [001](archive/001_input_contract_and_baseline.md) | 官方输入契约与基线 | 完成，已归档；五例共 136 拍一致，资产及生命周期证据齐全 |
| [001b](archive/001b_runtime_comparison.md) | 官方控制路径对照 | 完成，已归档；原生 Word 输入、五例真权重和远端 7 项测试通过 |
| [002](archive/002_nemotron_streaming_integration.md) | Nemotron 在线接入 | 完成，已归档；r4-asr 退出 0 |
| [003](archive/003_kokoro_playback_integration.md) | Kokoro 分段播放 | 完成，已归档；[003d修复](archive/003d_segment_continuity.md)及[003c用户复听](archive/003c_audio_listening_review.md)通过 |
| [004](004_training_data_and_annotation.md) | UltraChat micro-turn 数据管线 | 进行中；正式1000/200/300构建、审计及审查材料导出作业已提交，人审待完成 |
| [005](005_training_runtime_and_resource_probe.md) | 训练恢复与资源短跑 | 进行中；公共加载与独立零更新工具已实现，单卡验证已提交 |
| [006](006_punctuation_robust_adaptation.md) | 三组有限适配 | 待办；004、005 及 007 开训前准备未完成 |
| [007](007_turn_control_evaluation.md) | 独立话轮评测 | 待办；评测器、独立样本与候选报告未交付 |
| [008](008_full_chain_fdb_acceptance.md) | 真实音频与 FDB 验收 | 进行中；B0完整链路0/5，候选及FDB待验收 |

远端执行见 [001 任务单](archive/001_remote_execution.md)与 [002/003 任务单](archive/002_003_remote_execution.md)。001 只验证一套官方配置：Kyutai Word 逐词 strip、每拍空格连接、首非空 Word 起拍、600ms、BF16、64-token 贪心。raw 字符增量和 160ms 超时释放残词均不等同官方 Word；不展开时钟、发布粒度与句读矩阵。旧 raw/超时残词报告只作诊断；新原生 Word 五例全部通过，结果见 [001 验收报告](../../reports/layer1_training/issue001-word-20261019/README.md)。

[008a 官方权重完整链路诊断](archive/008a_official_full_chain_smoke.md)已完成：当前五例新正文/语音0/5，共178拍无协议/组件错误；已转入004/005训练准备，正式梯度更新尚未启动。

## 依赖与交付

004工具实现[013](archive/013_layer1_data_pipeline_implementation.md)、[来源恢复](archive/004a_source_download_recovery.md)与[016来源隔离](archive/016_external_data_exclusion.md)已完成归档；用户取消FDB补转写及其训练前置条件。[完整数据任务](004_remote_data_execution.md)与[017加载/零更新](017_training_loader_zero_update.md)继续跟踪实际产物，不能把代码或来源验真当正式训练放行。

[018正式数据交付](018_layer1_data_delivery.md)按用户决定先有限抽取最多6000原始对话再过滤/去重/切分，取消全库过滤及其CPU作业；当前在调试机1CPU/nice10/2GiB硬限运行r3。产出正式切分、32/100子集、机器审计及待签署材料；扩充集抽查使用同一正式数据，不增加训练规模。

[015 调试机资源实测](archive/015_debug_node_data_validation.md)完成：32条诊断在1CPU下约6.9秒、峰值约150MiB；同规模轻量检查直接在调试机受限执行。r4测试/诊断及完整来源下载最终均通过退出0。

文本训练路径为 001 → 004/005 → 006 → 007 → 008。004 数据工具、005 加载准备和 007 评价规则可在正式训练前推进；005 最终短跑依赖 004 最小集。002 轨迹用于 007 独立迁移评测，003 接入与人工试听已完成归档。006 交付训练资产及 dev 报告后由 007 选择和验收候选，008 最后完成新组合音频及 FDB；不重开选型、不实现 Layer 2/3。

| 已确定路线 | 必须交付的证据 | 主责 |
| --- | --- | --- |
| 使用论文采用的 UltraChat | 实际 revision/split/许可、原始 ID 与摘要、1,000/200/300 切分；精确作者 50k 清单未知时如实记录 | 001、004 |
| 自行实现 micro-turn 生成 | 论文参数映射、事件/监督/句读混合、固定种子审计与测试 | 004 |
| 从官方 checkpoint 继续训练 | 完整恢复、零更新对齐、仅已有 q/v LoRA 更新、训练状态恢复与可重载资产 | 005、006 |

## 共用约束

- 遵循[工程方案](../engineering_implementation.md)和[研究范围](../research_design.md)。状态使用待办、进行中、阻塞、完成，完成时记录提交、run_id、结果路径和遗留问题。
- 修改现有文档时直接维护当前版本；实验过程和失败保留在报告，避免重复追加互相更正的计划。实现优先修改现有模块，代码与同路径中文说明同步，文件名、注释和提交消息使用英文。
- 本地和远端使用 conda；真实模型及集群测试在远端调度作业执行，冻结两仓库源码、资产、数据、种子、时钟和预算，独立 run_id，保留失败及退出码。
- 保持五类控制 token、完整生成历史、唯一协议执行/仲裁路径与唯一播放所有权；已播放内容不可撤销，Layer 3 仅能修订未提交片段。
- 001/004/007 在候选结果前冻结数据和评价门槛；005 实测冻结训练配置。不得用 test/FDB 调参，不以成功样本均值掩盖漏答。音频目标均值约 1s、上限 1.5s，简单问题亚秒，008 补齐实际停播与 FDB 门槛。

## 归档

已有完成实现：[001a 资产扫描](archive/001a_asset_inventory.md)、[001c 历史保持](archive/001c_runtime_history_preservation.md)、[001d 加载压力](archive/001d_checkpoint_load_memory.md)、[001e 校验耗时](archive/001e_prompt_validation_overhead.md)、[002 接入](archive/002_nemotron_streaming_integration.md)、[002a WAV 读取](archive/002a_warmup_wav_format.md)、[003a 音色加载](archive/003a_local_voice_loading.md)、[003b 分段计时](archive/003b_segment_word_boundaries.md)。

文档维护：[009 进度核对](archive/009_issue_progress_audit.md)、[010 官方输入核实与计划收敛](archive/010_issue001_scope_reduction.md)。001/001b 和远端任务单现已基于新证据完成归档；训练仍受 004/005 等前置约束，保持 false。

远端维护：[011 清理无用环境与目录](archive/011_remote_storage_cleanup.md)完成并归档。Qwen3-ASR模型/专用环境及旧ASR/TTS选型开发实现已删除，原始结果和现役资产保留；主清单约6.25GiB目标占用已清理。

[012 主目录归拢](archive/012_remote_home_consolidation.md)已完成：24个历史目录归入interclarify-archive，顶层目录50→26；当前路径按[远端目录约定](../remote_workspace.md)和迁移清单查找。

[014 实际缓存/退役资产回收](archive/014_remote_cache_reclamation.md)已完成：直接删除14个编译缓存、3组候选权重、2套旧环境，目标删除前占用约20.58GiB；当前模型、训练环境和原始结果保留。
