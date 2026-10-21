# 最终候选权重加载

`scripts/runtime/layer1_candidate.py` 在官方 DuplexCascade 权重完整恢复后加载已登记的最终 LoRA 候选，不创建新 adapter、不恢复优化器或训练随机状态，也不拥有音频播放。

## 核心方法

`load_candidate(loaded, path, checkpoint, base_model)` 依次核验：

- 候选 `purpose/condition/arm` 属于已登记组合，且训练 summary 与 manifest 均标记正式完成；
- 步数与数据游标达到最终 epoch；
- checkpoint 文件摘要、训练引用资产与训练前参数摘要一致；
- 只包含既有 q/v LoRA 白名单，shape/dtype 匹配且数值有限；
- 恢复后的完整参数摘要与训练最终摘要一致。

验证通过后才复制 LoRA 参数，并用训练末尾保存的 prompt IDs 在干净进程中按相同 BF16/贪心/EOS/64-token 预算复现生成 IDs，结果写入服务健康信息。该检查证明候选可重载，不证明 FDB 或澄清能力。

当前登记 `T2_R3_delayed_start` 与 `ASR_R4_delayed_punctuation` 两个历史候选；新路线训练候选需要在此登记新的三元组。
