# 正式数据机器验收原件

issue004-build-r3生成、机器审计及审查材料导出全部完成，exit_code.txt为0。dataset/manifest.json绑定来源、配置、tokenizer、代码及1500份逐对话产物摘要；仓库只回收元数据和32条审查材料，全部训练正文/序列仍留远端。

| 检查 | 结果 |
| --- | --- |
| 原始抽样／过滤后候选 | 6000／5730 |
| train／dev／内部文本test | 1000／200／300 |
| 跨集合ID／分组／近重复 | 0／0／0 |
| T3训练原样／去句读 | 500／500 |
| 每臂序列总数 | 1812；三臂共5436 |
| 基础micro-turn总数 | 284378 |
| 每臂有效监督token总数 | 1762555 |

audit_build.json保留生成结束时的原审计。audit.json为源码8dd1546按用户32条签署口径重验的报告：机器通过，expanded_review_required=false，minimum_32_human_review_passed=false，parent_issue_complete=false。人工项尚未签署，training_allowed保持false。dataset/human_review.json当前仅登记政策，所有reviewer/accepted仍空，未伪造用户批准。

[32条审查目录](../review_32/README.md)为用户入口；review/minimum_32.md是原始合并版，review/selection.json与120事件模板仅为可选辅助，不是用户关闭004的额外任务。005/007继续作为后续训练门禁。
