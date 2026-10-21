# 最终候选权重加载

078登记独立的`ASR_R4_delayed_punctuation`候选，与原`T2_R3_delayed_start`分别限定purpose/condition/arm三元组；其余检查仍要求完整官方初始化一致、最终epoch、精确112个q/v LoRA、冻结状态一致及干净进程生成ID复现，不能仅更改标签加载任意权重。

`scripts/training/layer1_candidate.py`在完整官方模型恢复之后加载已登记最终T2_R3或ASR_R4 checkpoint，不创建新LoRA，不恢复optimizer或训练RNG，不拥有音频播放。

`load_candidate`要求purpose/condition/arm为已登记组合，训练summary成功且步数/游标达到配置和索引规定的最终epoch；checkpoint摘要必须匹配。随后复核训练引用的固定资产和训练前完整参数摘要，只接受完整既有q/v LoRA白名单及相同shape/dtype，全部验证后再复制。加载后完整参数摘要须与训练最终摘要相同，拒绝冻结参数改变或部分adapter。

干净进程使用训练末尾保存的 prompt IDs 按相同 BF16/贪心/EOS/64-token 预算生成，要求原始生成 IDs 完全一致；这证明候选重载，不证明 FDB 效果。返回条件、步数、完整还原及复现结论供服务健康信息和报告使用。旧 006 T1/T2/T3、036 T2_R2 和探针候选分支已删除。
