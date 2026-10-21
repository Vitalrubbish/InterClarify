# Layer 1 最终训练器

077/078新增ASR臂，`ProbeDataset`通过`arm_view`读取`asr_delayed`，独立统计`view_asr_delayed`；数据摘要、逐产物重编码和mask检查保持相同要求。078将使用独立协议及新索引，旧040训练身份不改写。

ASR运行按所选arm比较完整索引，并将`asr_surface.py`加入训练代码身份；命令行仅增加已登记ASR选项，序列长度、单卡要求、加权目标归一化和尾批处理不变。

`scripts/training/train_layer1.py`执行登记的040 T2_R3或078 ASR_R4全量单epoch训练。`--config`、`--protocol`、`--arm T2/ASR`与1,000条`--dialogues`均为必填；入口先调用`validate_delayed_config`按协议分支核验用户授权、加权loss、数据audit、完整索引、资产和预算，再加载官方权重。

`ProbeDataset`核验数据清单、机器审计、tokenizer、训练子集、逐对话缓存和事件计划，只读取train的登记视图，单进程、无预取worker。`validate_sequence`逐span检查消息头/历史mask、assistant目标与causal shift；`collate`右侧padding并屏蔽padding labels。

训练始终使用五类控制加权CE：先累计整批权重分母，再按micro-batch反向，loss、梯度、普通CE与五类计数/NLL逐步写入`steps.jsonl`。`save_checkpoint`保存112个LoRA张量、AdamW、scheduler、RNG、步数和游标；`restore_checkpoint`拒绝配置、数据、资产或源码不一致。中间保存点只用于恢复/排错，最终协议规定的epoch checkpoint是唯一候选（040为1,235步，078重新清点）。

输出目录拒绝覆盖，训练输出 5GiB、空闲盘 5GiB，整体 8 小时上限；每步记录显存、RSS、吞吐和预算。训练结束生成完整摘要并在独立进程重载候选、复现协议生成 IDs。`record_failure` 只写入本次新建目录；`compare` 保留连续/恢复运行的精确对照。`index` 子命令、006 四配置、036 对齐探针和普通 CE 路径已随旧设计删除。
