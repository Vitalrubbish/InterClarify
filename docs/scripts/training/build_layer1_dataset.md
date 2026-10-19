# 构建 Layer 1 数据

`scripts/training/build_layer1_dataset.py` 是构建命令入口，无独立业务类。`parser` 定义显式资产/来源/排除/长度/输出参数；`build` 依次验真来源、建立完整 SQLite 分组索引、选择对话、冻结事件和视图、编码序列、保存映射及人工审查模板。

输出目录包含 `manifest.json`、`dialogues.sqlite3`、`dialogues.json`、`view_assignments.json`、`smoke_subsets.json`、`human_review.json` 及按对话 ID 摘要命名的 `dialogues/*.json`。manifest 记录配置、两份来源清单摘要、代码/tokenizer 摘要、Git 提交、排除统计、已完成对话游标和逐产物摘要。每对话产物保留 plan 和 T1/T2/T3 序列，包含 source_type、split、epoch、事件跨度、IDs、labels、attention_mask 和有效监督数。

必须提供 JSON 外部排除清单，字段为 `ids`、`normalized_hashes`、`source_refs`（字符串列表）、`reviewed`（布尔值）；规范化摘要为核心模块 `digest(normalized(text))`。reviewed=true 要求非空 source_refs；只有实际核对外部来源后才能登记，空清单不表示完成 FDB/FLEURS 隔离审查。原始来源只读取已冻结 UltraChat，不把外部评测语料加入候选集。

FDB转写不作为训练前置。构建manifest额外保存exclusion_review_scope和optional_text_coverage_complete，区分来源清点与可选全文重复检查；text_coverage_complete=false不新增阻塞，训练只读UltraChat的约束不变。旧清单无范围字段时登记legacy_manifest，不擅自声称全文覆盖。

最小 train 的前 32/100 条 ID 单独列出。`human_review.json` 逐条保存待审路径、摘要、reviewer、accepted；初始均未完成，不自动伪造人审。

`--resume` 要求配置、代码、tokenizer、来源、排除清单、epoch 和 max-length 全部一致；已有完整对话逐项验摘要，未完成对话从稳定种子重建。完整建库中断尚不支持行级恢复，只要已有合格或排除行就明确报错并要求新目录，避免重复累计过滤记录。开发/测试计划不随训练 epoch 改变。所有构建结果固定 `training_allowed=false`，后续 005/007 门禁独立处理。

018采用全源过滤后6000候选去重。manifest的accepted_source_dialogues仍统计完整来源合格对话数，不以候选数量代替；source_sampling单独列完整扫描行数、候选预算/实际数量及近重复分组范围。中断检查同时包含source_inventory，扫描尚未完成时不得直接重用半成品索引。
