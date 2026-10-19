# 完整官方权重公共加载模块

`scripts/training/layer1_model.py`向推理服务和训练路径提供同一套完整恢复逻辑，不启动HTTP或播放。`LoadedCheckpoint`封装tokenizer、PEFT模型、带llm层级的wrapper、配置、token映射、加载及可训练参数审计。

`load_official_checkpoint`保持原服务的base加载、resize、q/v LoRA结构、modules_to_save、BF16、先上设备再恢复完整state的顺序；`restore_state`在任何复制前核验完整keys和shape，再strict=True恢复。`normalize_state_dict`只允许已登记q/v weight/bias到base_layer的迁移，映射碰撞/未知/缺失均拒绝。推理模式全部冻结并eval，训练模式完成恢复后才开放白名单。

`configure_trainable`按精确完整名称及模型层数验证每层q/v LoRA A/B default全部存在，只开放这些张量；embedding/head及其modules_to_save副本、基础参数和其他adapter不更新。白名单缺项时重新冻结并失败。首轮不创建额外adapter、不改变r/alpha/dropout。

`verify_asset_inventory`流式复核001冻结inventory中checkpoint、base及官方源码逐文件大小/SHA256，不以revision hint代替内容校验。`state_fingerprints`以有界CPU块散列每个state张量，记录dtype/shape，用于验证独立恢复内容及零更新前后不变。该摘要反映实际设备dtype下的恢复值，原始文件摘要另存。

`validate_prompt_ids/validate_state_keys`由服务重导出以保留调用契约。训练加载没有复制FastAPI生命周期，官方独立参考也不调用本模块的恢复/迁移函数。
