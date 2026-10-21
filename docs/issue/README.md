# 开发与测试工作单

更新：2026-10-21。这里只列当前工作与采用决定；已完成过程记录统一见[归档索引](archive/README.md)。

## 当前工作

| 工作单 | 状态 | 范围与入口 |
| --- | --- | --- |
| [077：延后句读重建原1k](077_layer1_delayed_punctuation_rebuild.md) | 进行中 | 固定原切分/事件监督，新增ASR因果可见视图，远端重建并审计 |
| [078：新ASR视图1k训练](078_layer1_delayed_punctuation_training.md) | 等待077 | 用户已授权；同一官方初始化、单卡单epoch，索引重算并冻结后启动 |
| [074：训练集扩充至3k并保证多样性](074_layer1_diverse_3k_dataset.md) | 待执行 | 073已交付；保留原1k来源与固定dev/test，新增2k独立对话，按ASR表面形式冻结新视图 |
| [075：远端多卡训练可行性调研](075_layer1_multigpu_feasibility.md) | 待执行 | 远端资源与环境核查、训练器差距、单卡/多卡成本比较；可与073独立推进 |

任务完成后归档；执行、传输通过和模型能力通过分别记录。归档清理不会改变当前远端作业或把未执行项记为通过。

## 当前采用决定

| 内容 | 采用范围与依据 |
| --- | --- |
| 研究范围 | [research_idea.md](../research_idea.md)；模型自主发现任务信息缺口并判断澄清时机，系统backchannel为后续方向，尚未接入 |
| 思考调用方向 | Layer 1 在倾听或表达时均可通过独立 special token 请求异步思考，每会话最多一个请求在途，合并重复触发；结果写回 Layer 1，调用 token 不进入 TTS，表达经过统一仲裁和单一播放路径；其余协议未定、尚未实现，见[研究草稿第 7.1 节](../research_idea.md#71-思考与表达的模块关系) |
| ASR / TTS | Nemotron EN 0.6B/160ms + Kokoro 82M/af_heart；[ASR报告](../asr_selection_report.md)、[TTS报告](../tts_selection_report.md) |
| TTS / KV | 首段300ms、后续1200ms，600ms micro-turn，跨请求按会话KV复用；用户接受自然度略逊600ms但整体差异不大，[047](archive/047_tts_first_segment_latency.md)、[048](archive/048_cross_request_kv_cache.md) |
| 生成策略 | duplex_greedy_v1，显式greedy/单beam/repetition_penalty=1.0；固定108对回归一致，不外推全部BF16输入恒等，[061](archive/061_explicit_generation_policy.md) |
| 运行源码 | [选定X-Talk版本](../../configs/xtalk_runtime_source.json)：`d6dc3bf`已推送origin/dev；[当前配置](../configs/xtalk_duplex_english_runtime.md) |
| 延迟与后续方向 | [分段延迟报告](../latency_analysis_report.md)；完整链路历史时延与新策略固定请求回归分别标注，backchannel可降低首反馈延迟/感知等待，实际收益待测 |
| 当前候选与下一阶段 | T2_R3_delayed_start保留1k基线；用户现已授权077重建原1k与078重训，先检验新ASR视图；074的3k扩充、075多卡调研暂不执行 |
| 训练文本与ASR形式 | [073审计](archive/073_layer1_pause_punctuation_audit.md)确认T2过度删除内部句读；用户补充句末标点常在下一句开始后才出现。074需按标点到达可见性构造增量，迟到标点不提前泄漏、不回填已消费历史，并补核符号种类及上下文重置。原数据未改，人审pending，新训练尚未放行 |
| 完整FDB两轴结果 | 319例回放和官方转写完成，退出码均0；Smooth TOR 59/119、平均延迟1.023秒，Interruption TOR 160/200、平均延迟1.183秒；延迟只含有效接话，GPT相关性待补，[最终报告](../../reports/fdb/20261021-full-two-axes-r4/README.md) |

## 共用约束

- 中文开发文档；英文文件名、实现注释与提交消息。实现修改同步同路径说明，先记录设计变更再改代码。
- 保持Layer动作边界、单一仲裁器与单一TTS播放所有权；已听内容不可撤销，Layer3只修订未提交片段。
- 本地和远端使用conda；真实模型与集群测试在远端调度执行，冻结源码/资产/输入及资源上限，独立run_id，保留失败与退出码。
- 完整模型历史和生成ID保留；缓存改写/取消/淘汰时安全失效重建。数据和FDB不用于未授权训练或临时调参。
- 未执行的官方评分、完整评测、人工复核继续如实标注；统计延迟时同时报告漏答与样本覆盖率。
- 大模型、音频、逐请求日志留本地/远端；Git保留当前源码、简明报告、关键摘要与追溯哈希。

## 历史追溯

[归档索引](archive/README.md)保留已完成工作单的固定Git原文入口。训练/加载/组件接入、旧执行预算和研究草稿修改均按当时提交追溯，不作为当前运行前置。历史维护和远端路径另见[证据索引](../baseline_evidence.md)、[远端目录约定](../remote_workspace.md)。
