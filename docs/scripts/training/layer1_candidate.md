# 最终候选权重加载

`scripts/training/layer1_candidate.py` 在完整官方模型恢复之后加载最终 `T2_R3_delayed_start` checkpoint，不创建新 LoRA，不恢复 optimizer 或训练 RNG，不拥有音频播放。

`load_candidate` 要求 purpose 为 `issue040_delayed_start`、条件为 `T2_R3_delayed_start`、arm 为 T2，训练 summary 成功且最终步数/游标为 1,235/2,469；checkpoint 摘要必须匹配。随后复核训练引用的固定资产和训练前完整参数摘要，只接受完整既有 q/v LoRA 白名单及相同 shape/dtype，全部验证后再复制。加载后完整参数摘要须与训练最终摘要相同，拒绝冻结参数改变或部分 adapter。

干净进程使用训练末尾保存的 prompt IDs 按相同 BF16/贪心/EOS/64-token 预算生成，要求原始生成 IDs 完全一致；这证明候选重载，不证明 FDB 效果。返回条件、步数、完整还原及复现结论供服务健康信息和报告使用。旧 006 T1/T2/T3、036 T2_R2 和探针候选分支已删除。
