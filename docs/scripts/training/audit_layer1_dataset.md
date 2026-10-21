# 审计 Layer 1 数据

077增加按配置识别ASR臂，所有视图继续重新编码并检查监督覆盖；`audit_asr_surface`另外核验可见文本/来源守恒、延后补点和无未来字符，统计写入`asr_surface`。旧数据仍只检查原三臂，原审计文件不覆盖。

`scripts/training/audit_layer1_dataset.py` 为独立审计入口，无业务类。`audit` 复核 manifest、tokenizer、对话/事件/视图摘要、配置规模、对话 ID 和去重组唯一性，另外对已选集合逐对精确检查跨 split 的近重复。它重建固定种子的事件与序列，比对所有 IDs、mask、目标跨度和分拍，检查 user/消息头不参与 loss、沉默控制无正文、自然停顿仍等待、用户附和继续正文以及每个事件每臂只监督一次。

019新增语义门禁：凡有原文跨度的用户事件，原样与去句读文本都必须非空；否则即使序列可重建也不通过机器审计。报告同时记录标点独占片段合并次数及合并后超过7基础token的用户片段数，避免把新的边界例外隐藏在机器通过状态中。

报告分别列对话、序列、micro-turn、有效监督 token 数，控制/事件类别、长度、T3 分配、来源及排除计数，以及 32 条人审和外部排除状态。停顿/插话/附和单列触发数、合格采样分母、观测频率及采样单位，分母为零保留null；pending按实际状态列出人审/排除审查和005/007。`machine_passed=true` 仅代表机器审计，不自动完成父 issue，不自动放行训练。异常保存失败报告并非零退出；不能删除失败对话后继续宣称规模满足。

外部审查同时报告exclusion_review_scope及optional_text_coverage_complete。来源清点通过即不再pending external_exclusion_review；可选FDB文本检查未覆盖不影响这一状态，不要求为测试集补转写。其他人审、数据/权重门禁仍保留。

source_sampling报告实际抽样/读取预算、过滤计数及full_source_filtering=false，近重复图只覆盖抽取的候选集合；最终train/dev/test仍独立逐对检查同一Jaccard阈值，不能将抽样检查外推为147万条全库已过滤/去重。

人工最小审查必须覆盖 train 前 32 条，对应产物摘要、reviewer 和 accepted=true 全部齐全。扩充审查记录在 expanded_behavior_reviews：每项包含 dialogue_id、sha256、event_id 及 reviews 列表（reviewer、accepted）。expanded_review_complete 要求实际覆盖五类控制、至少一个事件有两名不同审查者通过、complete=true，不能只手写一个布尔值。正式交付仍需核实抽样充分性和意见分歧，不替代父任务验收。合成文本保留集可能被官方预训练见过，报告明确标 unknown。

按本轮用户决定，human_review.json的policy=user_minimum_32_signoff表示004以32条用户签署收口，扩充抽查仅记录可选状态，不再加入pending或阻塞parent_issue_complete。仍逐条核对32个ID/产物摘要及人工签署，source_review和机器检查必须通过；005/007继续列在训练pending且training_allowed=false。旧policy未指定时保留原扩充检查，以免改变历史报告的原口径。

r5审计逐用户长轮核验数值转换映射及无残留数字，再按规范化跨度验证事件；报告替换类别计数。显式user_waived_after_machine_audit政策要求构建身份与review中的非空豁免理由一致，跳过人审待办而不填签署通过；005/007仍保留，training_allowed=false。

r5同时以原始文本与数值规范化后的文本进行切分前近重复分组、切分后跨集合审计，避免书面数字和英文数词在转换后变成跨集合重复；外部排除摘要也检查规范化后的用户文本。

## 延迟启动时序审计

`audit_response_timing` 固定检查当前唯一时序：每个源用户轮的跨度连续、完整且只消费一次；每个末用户片段后紧接空用户的 response_start；末片段按普通/单片段插话分别为 talking/interruption，均无正文；response_start 必须为 finish 且有首段正文。非启动事件不得输出 finish，句内暂停仍 talking；完整回答或插话截断前缀必须与源 assistant 编码一致。计数汇入机器审计。

数据构建与审计不再接受旧 `same_user_chunk` 模式，也不再提供 `--baseline-dataset` 新旧对照参数；当前延迟数据已按固定时序构建并审计，历史对照仅保留在固定 Git 提交。
