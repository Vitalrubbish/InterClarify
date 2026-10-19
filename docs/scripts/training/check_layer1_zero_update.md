# 训练加载零更新对照

`scripts/training/check_layer1_zero_update.py`是005的独立恢复验证入口，无长期运行服务。`run`先验真官方/base/checkpoint，`freeze_prompts`从001已冻结独立reference记录选15个prompt并物化配置、输入及源码摘要；随后用两个干净子进程串行运行reference/candidate，避免两套7B权重同时占显存。

`load_reference`按已冻结model.py内容摘要导入原版Model，用本地base路径和BF16构建相同结构；按独立写出的q/v基座键规则核对全部keys/shape并strict恢复。原版server.py使用strict=False，本对照明确收紧为完整恢复，不能把不完整恢复当参考。BF16及限定最后位置logits是已登记本项目运行设置，与001一致，未修改原版Model文件。

`worker`候选调用公共加载器并仅开放现有q/v LoRA，然后eval关闭dropout。每个prompt使用同参数greedy generate，`output_logits=True`保存每个生成步完整词表raw logits为float32 safetensors，同时保存生成IDs及SHA256。全部权重在前后分块散列，变化立即失败；报告保存strict映射及trainable名称/数量。零更新不创建optimizer、不反向传播。

`compare_outputs`复核logits文件摘要、prompt和案例身份、两套恢复后逐张量摘要完全一致；每步全词表logits按已登记容忍比较，生成IDs须完全一致。缺输出、shape不符、非有限值、权重变化均失败；失败写failure.json、非零退出。每个模型子进程600秒上限，外层作业另有限时。

入口显式接收checkpoint/base/official-source/output；默认config和inventory来自仓库固定文件。`--worker`为内部子进程模式，正式验收必须走外层run，不能用单worker输出冒充通过。通过只说明恢复与零更新，不证明梯度、optimizer/RNG恢复或正式训练放行。
