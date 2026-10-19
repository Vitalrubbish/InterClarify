# 发布 tokenizer 数据诊断

`scripts/remote/probe_layer1_data.py` 是有界 CPU 诊断入口，无业务类。`probe` 核对固定来源身份与首个原始 shard 的完整大小/SHA256，加载发布 tokenizer，读取前 32 条符合过滤规则的真实对话，生成固定事件及原样/去句读序列，检查种子确定性和监督一致性，保存计划与紧凑报告。

`--samples` 限 1–100，默认 32，`--max-length` 默认 4096。诊断只验证首 shard、代码和真实 tokenizer，不建立全库去重或正式切分；报告固定 diagnostic_only=true、full_source_verified=false、training_allowed=false、human_reviewed=false。这些样本不是已通过人审的004训练最小集，不得转入006。

按2026-10-19用户明确要求，23项轻量单元测试及32条诊断允许在远端调试机直接执行：先检查可用内存，子进程绑定1个CPU、nice=10、线程1、虚拟地址空间硬限2GiB、CPU时间180秒、墙钟360秒，并记录峰值RSS/退出码。命令仍使用独立conda和冻结源码；不加载模型、不在调试机做全库建索引或训练。

原计算作业现已完成23项测试与32条诊断，正在唯一实例续传来源，保留它的已有进度。调试机此次仅补做32条资源测量，耗时6.894秒、峰值RSS约149.94MiB、退出0，不重复单元测试、不启动第二个下载器。计算作业的完整数据生成仍按4CPU/32GiB等实际测量安排，见 [015](../../issue/archive/015_debug_node_data_validation.md)。
