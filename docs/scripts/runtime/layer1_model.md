# 完整官方权重公共加载模块

`scripts/runtime/layer1_model.py` 向推理服务提供 DuplexCascade 官方权重的完整恢复逻辑，不启动 HTTP、训练或播放。

## 核心设计

- `LoadedCheckpoint` 封装 tokenizer、PEFT 模型、带 `llm` 层级的 wrapper、训练配置、token 映射与加载信息。
- `load_official_checkpoint` 按“建立 base 结构、resize、创建 q/v LoRA、移到设备、严格恢复 state”的顺序加载，避免 CPU 同时驻留两套完整模型。
- `normalize_state_dict` 只允许已登记的 q/v `weight/bias` 到 PEFT `base_layer` 键迁移，拒绝映射碰撞、未知键和缺失键。
- `validate_prompt_ids` 一次读取词表大小后严格检查所有 token；`validate_state_keys` 在复制前核对完整键集合。
- `verify_asset_inventory` 流式复核冻结清单中 checkpoint、base 与官方源码的逐文件大小和 SHA256。
- `state_fingerprints` 以有界 CPU 块散列每个张量，记录 dtype/shape，用于比较独立恢复结果。
- `configure_trainable` 只开放每层 q/v LoRA 的 A/B `default` 权重，其余参数保持冻结。

## 边界

该模块不拥有会话、生成策略、缓存或音频播放；这些分别由 `duplex_model_service.py`、X-Talk 运行适配器和 TTS 路径负责。真实 7B 加载只在远端 GPU 作业中执行。
