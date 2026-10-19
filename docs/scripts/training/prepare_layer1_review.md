# 正式数据人工审查材料导出

`scripts/training/prepare_layer1_review.py`从机器审计通过的正式数据中导出可读材料及待签署模板，无业务类，不调用模型作裁判。

`prepare`核对完成状态、审计对应manifest摘要、原始切分、tokenizer及逐对话产物摘要。前32条训练对话导出全部原文、全部事件、用户两种句读视图、控制名和解码后的assistant目标，写minimum_32.md。expanded_samples.md保存分层抽查事件、相邻拍和原始对话上下文，便于判断插话、附和及停顿标签是否合理。

`choose_events`按固定种子/行为/split/对话ID/event ID计算稳定排序，同类每对话仅选一个事件。默认每类20条，train/dev/test为12/4/4，共6类120条；每类4条需双人复核，总计24条。候选不足在coverage中报告，禁止重复填充或按模型表现选样本。用户续说与自然停顿虽然都可监督speaking，分开抽样以检查误接话。

human_review_template.json只含reviewer/accepted/reason为空的模板，完整数据的human_review.json不自动覆盖；人工完成后按相同schema回填对应原件，再重跑审计。selection.json绑定原始摘要和固定样本，summary.json记录实际覆盖并始终保持human_review_complete=false/training_allowed=false。它不增加数据或训练曝光，也不替代真实人工签署与部分独立双人复核。

参数显式指定dataset/audit/tokenizer/output；默认seed=20261018、per-behavior=20、double-per-behavior=4，预算在018预登记。4096只作数据窗口审计，训练长度待005冻结。
