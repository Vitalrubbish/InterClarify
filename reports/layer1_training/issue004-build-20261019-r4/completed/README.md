# r4 机器验收原件

`dataset/manifest.json` 绑定1500条对话的来源、配置、tokenizer、代码与逐产物摘要；`audit.json` 是固定源码对全量计划、序列、监督和空用户片段的重建检查。仓库仅回收元数据和32条人工材料，全部训练序列保留在远端。`exit_code.txt=0`，按用户最小32条审计政策重审的 `policy_reaudit_exit_code.txt=0`。

| 检查 | r4 结果 |
| --- | --- |
| 原始抽样／过滤后候选 | 6000／5730 |
| train／dev／内部文本test | 1000／200／300 |
| 跨集合ID／分组／近重复 | 0／0／0 |
| T3训练原样／去句读 | 500／500 |
| 三臂监督序列总数 | 5394 |
| 基础micro-turn总数 | 281260 |
| 每臂有效监督token总数 | 1757335 |
| 标点片段合并／超过7基础token片段 | 2355／336 |
| 有来源且去句读后为空的事件 | 0（全量机器审计门禁） |

`audit.json` 中 `machine_passed=true`、`human_review_policy=user_minimum_32_signoff`、`expanded_review_required=false`、`minimum_32_human_review_passed=false`，训练仍不放行。清单摘要为 `006dcac7c359ae1436bfe1b168c8102827f5b017c06ab955ae7bb048a6382acb`。人工审计对象为[32条逐条材料](../review_32/README.md)，所有签署字段保留空值。
