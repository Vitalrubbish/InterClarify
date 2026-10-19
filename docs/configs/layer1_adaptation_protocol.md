# Layer 1 适配协议登记

`configs/layer1_adaptation_protocol.yaml` 是实验登记文件，不是产品启动配置；无类或方法，现有远端入口不会自动读取它。`runtime` 记录组件和生成设置，`assets` 记录来源与核验状态，`data/training` 固定数据和有限继续训练方案，`diagnostic` 登记 001 单套参考对照，`acceptance/gates` 记录候选门槛和未完成证据。

001 的官方输入依据是 [server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422-L499)：接收 Kyutai Word，逐词 strip、每拍空格连接；首个非空 Word 起拍，600ms、64-token 贪心，推理精度保持本项目冻结的 BF16。`diagnostic.input_contract` 指定该语义，`input_manifest` 和 `evidence_report` 已指向 2026-10-19 验收证据；原件摘要与紧凑副本摘要分开保存，五例 136 拍通过，`issue001_runtime_comparison: passed`。

旧 raw 字符增量和 160ms 超时释放残词的 complete_word 不等同官方 Word，本轮已从比较器删除，仅保留历史报告。001 不再展开配置矩阵；单步、固定输出仅用于定位具体差异，集成 reset/cancel 独立核对。产品仍为 Nemotron/Kokoro，`production_clock` 记录实际 session-start，产品迁移与音频验收由 007/008 完成。

同资产同 prompt 要求生成 IDs 一致，logits 容忍不允许改变控制选择。1ms 只用于逻辑事件归属，物理迟到、排队和完整请求耗时另报。`training_released: false` 只是登记状态，未来训练入口仍须检查全部前置证据；001 不要求官方权重达到接话率目标。`assets.licenses_reviewed: true` 表示来源与当前研究使用边界已核验，见本轮报告；不表示新增分发许可。

首轮最多 1,000 条、第二轮最多 3,000 条，每组每轮最多一 epoch，GPU 小时上限分别为 8/16，总计 72，最多 8×4090。005 根据实测冻结长度、batch 和步数；001 诊断预算 4 GPU 小时另计。训练只更新完整恢复的官方 checkpoint 中已有 q/v LoRA。

2026-10-19来源验真：UltraChat十个固定shard已下载完成并重新逐文件核对大小/SHA256，共9,288,990,895字节，下载和复核退出均0；source_files_download_verified更新为true，见[证据](../../reports/layer1_training/issue016-source-and-exclusions-20261019/source_verification.json)。用户取消FDB补转写要求，来源隔离登记已完成。r5全量数据审计已通过，用户明确免除新人工复审，issue004_data_audit更新为passed；005/007门禁仍未完成，training_released保持false。

r5登记user_numeric_surface=english_numeric_v1，完整用户轮先转换数值读法再分拍；decimal/time原始形式保存在映射，不再承诺模型输入保留原数字字符串。audited_dataset_manifest指向正式r5清单，human_review_policy明确记录用户豁免。原样/去句读/混合三臂共享这一前处理。

真实 dev 每行为至少 30 例，test 每行为至少 100 例、至少 20 位说话人且 dev/test 说话人不交叉；报告按说话人分组的 95% bootstrap 区间，样本不足时补充独立样本。004/007 在候选结果前交付清单，数值门槛见 YAML，不事后降低。质量使用盲标签评审；音频延迟归 008，均值上限 1.5 秒、简单问题亚秒覆盖下限 90%，漏答保留分母。
