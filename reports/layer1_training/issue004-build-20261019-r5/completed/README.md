# r5机器验收原件

- `audit.json`：全量重建1500条事件计划和5271个序列，核验来源、规范化映射、两种文本域跨集合近重复、特殊token、mask、窗口与目标覆盖，记录数值替换分布和用户豁免。
- `dataset/manifest.json`：固定原始UltraChat、tokenizer、配置、代码摘要和1500份逐对话产物摘要；训练正文/序列留远端，不全部回收进Git。
- `dataset/human_review.json`：`policy=user_waived_after_machine_audit`，理由与构建身份一致，所有reviewer/accepted仍空；`minimum_32_human_review_passed=false`如实表示未执行新的人工签署，父任务依据显式豁免完成。
- `effective_config.yaml`、`environment.txt`、`source_commit.txt`和`build.log`：实际规则、依赖、冻结源码和生成过程。
- `numeric_examples.json`：正式数据11类替换的最小来源跨度样例，不是新增审查材料。
- `exit_code.txt`：构建和审计入口最终退出0。

独立回收核对：manifest字节SHA256与audit.json一致，T3分配与清单一致，人工豁免理由与身份一致，没有新增人工签署；004完成，训练放行仍为false。
