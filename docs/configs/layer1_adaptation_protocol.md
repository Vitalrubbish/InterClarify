# Layer 1 适配协议登记

`configs/layer1_adaptation_protocol.yaml` 是父级实验登记文件，不是产品启动配置；无类或方法，最终 T2_R3 训练通过延迟协议间接读取其资产、数据、门禁和训练后评价字段。`runtime` 记录组件和生成设置，`assets` 记录来源与核验状态，`data/training` 固定数据和有限继续训练方案，`diagnostic` 登记 001 单套参考对照，`acceptance/gates` 记录候选门槛和未完成证据。

001 的官方输入依据是 [server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422-L499)：接收 Kyutai Word，逐词 strip、每拍空格连接；首个非空 Word 起拍，600ms、64-token 贪心，推理精度保持本项目冻结的 BF16。`diagnostic.input_contract` 指定该语义，`input_manifest` 和 `evidence_report` 已指向 2026-10-19 验收证据；原件摘要与紧凑副本摘要分开保存，五例 136 拍通过，`issue001_runtime_comparison: passed`。

旧 raw 字符增量和 160ms 超时释放残词的 complete_word 不等同官方 Word，本轮已从比较器删除，仅保留历史报告。001 不再展开配置矩阵；单步、固定输出仅用于定位具体差异，集成 reset/cancel 独立核对。产品仍为 Nemotron/Kokoro，`production_clock` 记录实际 session-start，产品迁移与音频验收由 007/008 完成。

同资产同 prompt 要求生成 IDs 一致，logits 容忍不允许改变控制选择。1ms 只用于逻辑事件归属，物理迟到、排队和完整请求耗时另报。`training_released: false` 只是登记状态，未来训练入口仍须检查全部前置证据；001 不要求官方权重达到接话率目标。`assets.licenses_reviewed: true` 表示来源与当前研究使用边界已核验，见本轮报告；不表示新增分发许可。

首轮最多 1,000 条、第二轮最多 3,000 条，每组每轮最多一 epoch，GPU 小时上限分别为 8/16，总计 72，最多 8×4090。005 根据实测冻结长度、batch 和步数；001 诊断预算 4 GPU 小时另计。训练只更新完整恢复的官方 checkpoint 中已有 q/v LoRA。

2026-10-19来源验真：UltraChat十个固定shard已下载完成并重新逐文件核对大小/SHA256，共9,288,990,895字节，下载和复核退出均0；source_files_download_verified更新为true，见[证据](../../reports/layer1_training/issue016-source-and-exclusions-20261019/source_verification.json)。用户取消FDB补转写要求，来源隔离登记已完成。r5全量数据审计已通过，用户明确免除新人工复审，issue004_data_audit更新为passed。

2026-10-20的005单卡试跑完成，完整状态恢复精确一致，issue005_zero_update_and_recovery更新为passed。当时按缓存保留后至少2GiB余量选择512，后续用户要求通过029切换2048；005探针结果已随旧路线证据清理删除；`issue005_zero_update_and_recovery`门禁记录保留。训练采样seed为20261020，数据生成seed仍为20261018，原4096事件计划不变。

029完成2048全量重编码：每臂2,428序列、1,193,875监督token及1,214优化器步，batch1/累积2。基于026实际100步循环149.910秒，首轮循环外推约0.5055GPU小时/臂；不含启动和评价。第二轮数据未构建，旧512估算撤下，耗时与round2_exact_steps保持null。原8/16小时及72总上限保留。030按用户选择移除独立dev评测开训要求，001/004/005已通过，training_released改为true；此值不表示正式训练已执行。

资源依据改为026单张4090/2048持续100步实测，`resource_policy=issue026_sustained_2048_user_selected`。`resource_min_headroom_gib=null`表示不再使用005缓存保留后2GiB的筛选策略，不表示显存无限或已验证全量长跑。正式索引指向029报告；每步继续记录显存与RSS，失败保留证据。

r5登记user_numeric_surface=english_numeric_v1，完整用户轮先转换数值读法再分拍；decimal/time原始形式保存在映射，不再承诺模型输入保留原数字字符串。audited_dataset_manifest指向正式r5清单，human_review_policy明确记录用户豁免。原样/去句读/混合三臂共享这一前处理。

真实 dev 每行为至少 30 例，test 每行为至少 100 例、至少 20 位说话人且 dev/test 说话人不交叉；报告按说话人分组的 95% bootstrap 区间，样本不足时补充独立样本。004/007 在候选结果前交付清单，数值门槛见 YAML，不事后降低。质量使用盲标签评审；音频延迟归 008，均值上限 1.5 秒、简单问题亚秒覆盖下限 90%，漏答保留分母。

## 2026-10-20 四配置启动准备

006首轮现为2048窗口；`training.round1_optimizer`登记正式AdamW、1,214步线性调度、37步warmup及每203步保存。030固定最终1,214步checkpoint用于训练后FDB测试，其他保存点仅作恢复与排错，不再是dev选择候选。

030删除已不适用的`evaluation_assets`和`issue007_pretraining_preparation`开训门禁，不实现独立回放器或内部自动内容质量计分。`post_training_evaluation`登记B0/T1/T2/T3在同一历史FDB小子集上运行当前Nemotron/Kokoro全链路；清单含25个历史input.wav会话及原始文件摘要，继续排除在训练外。输入使用原生ASR，不增加句读视图。`content_review=manual_after_inference`记录测试后的人工检查。原`acceptance`数值条目标注为后续独立验收范围，不作为本轮旧小子集能力报告门禁；内部内容计分阈值移除。

历史小子集用于回归与能力描述，不通过其分数更换checkpoint或宣称独立泛化验收。真实`acceptance.sample_manifest`仍可为空。原协议顶层`issue/status`继续表示001历史登记状态，不表示006训练已完成。
