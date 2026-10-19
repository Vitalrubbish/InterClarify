# 零更新对照登记

`configs/layer1_zero_update.yaml`固定BF16、单卡CUDA、64-token贪心、raw logits绝对/相对容忍0.02/0.01及生成ID完全一致，无类或方法。配置在模型运行前与fixture一起写入产物。

每个001历史案例从独立reference请求中取首/中/末三个不超过2048-token的prompt，共15例。只复用既有prompt IDs，不利用新候选结果选择输入；报告保留请求索引、原件摘要。限制prompt长度用于单卡有界验证，不代替长会话/完整136拍对照。

比较每个实际生成步完整词表的raw logits，不能只比较argmax或top-k。dtype相同、全部资产验真、模型eval关闭dropout；trained参数仅开放已有LoRA，零更新过程无optimizer。此配置不放行006，不替代005保存恢复或007开训前准备。
