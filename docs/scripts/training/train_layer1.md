# Layer 1 最终训练器

`scripts/training/train_layer1.py` 只执行 `issue040_delayed_start` 的 T2_R3 全量单 epoch 训练。`--config`、`--protocol`、`--arm T2` 与 1,000 条 `--dialogues` 均为必填；入口先调用 `validate_delayed_config` 核验用户授权、加权 loss、数据 audit、完整索引、资产和预算，再加载官方权重。

`ProbeDataset` 核验 r5 清单、机器审计、tokenizer、训练子集、逐对话缓存和事件计划，只读取 train 的 T2 去句读视图，单进程、无预取 worker。`validate_sequence` 逐 span 检查消息头/历史 mask、assistant 目标与 causal shift；`collate` 右侧 padding 并屏蔽 padding labels。

训练始终使用五类控制加权 CE：先累计整批权重分母，再按 micro-batch 反向，loss、梯度、普通 CE 与五类计数/NLL 逐步写入 `steps.jsonl`。`save_checkpoint` 保存 112 个 LoRA 张量、AdamW、scheduler、RNG、步数和游标；`restore_checkpoint` 拒绝配置、数据、资产或源码不一致。中间保存点只用于恢复/排错，最终 1,235 步 checkpoint 是唯一候选。

输出目录拒绝覆盖，训练输出 5GiB、空闲盘 5GiB，整体 8 小时上限；每步记录显存、RSS、吞吐和预算。训练结束生成完整摘要并在独立进程重载候选、复现协议生成 IDs。`record_failure` 只写入本次新建目录；`compare` 保留连续/恢复运行的精确对照。`index` 子命令、006 四配置、036 对齐探针和普通 CE 路径已随旧设计删除。
