# 外部评测排除配置

`configs/layer1_exclusions.yaml`登记五个FDB v1.0子集的完整样本数、FLEURS 100条、历史五例和允许提取的文本字段，无类或方法。范围沿用004：FDB为当前冻结v1.0五子集共727例，其他版本未加入时须登记，不能声称已覆盖未知版本。

只提取text/reference/context/interrupt等明确文本，忽略PAUSE/TURN-TAKING标记和时间/文件名。FDB和FLEURS ID不属于UltraChat命名空间，不按数字ID直接排除；保存原始ID作来源，使用规范化各轮/拼接摘要匹配。未提供转写的音频不能凭时间标注补造文本，coverage_complete/reviewed须为false。
