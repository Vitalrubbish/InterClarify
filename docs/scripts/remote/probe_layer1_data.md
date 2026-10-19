# 发布 tokenizer 数据诊断

`scripts/remote/probe_layer1_data.py` 是有界 CPU 诊断入口，无业务类。`probe` 核对固定来源身份与首个原始 shard 的完整大小/SHA256，加载发布 tokenizer，读取前 32 条符合过滤规则的真实对话，生成固定事件及原样/去句读序列，检查种子确定性和监督一致性，保存计划与紧凑报告。

`--samples` 限 1–100，默认 32，`--max-length` 默认 4096。诊断只验证首 shard、代码和真实 tokenizer，不建立全库去重或正式切分；报告固定 diagnostic_only=true、full_source_verified=false、training_allowed=false、human_reviewed=false。这些样本不是已通过人审的004训练最小集，不得转入006。

只能在远端调度 CPU 作业执行，4 CPU/8GiB、0GPU，最长5分钟；与后续来源恢复作业串行。先运行两组数据单元测试，再执行该入口，回收 report.json、测试和退出码，不回收全部原文。
