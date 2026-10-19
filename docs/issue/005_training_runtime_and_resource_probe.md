# Issue 005：恢复训练状态并完成远端资源短跑

状态：进行中（017真权重零更新已通过；服务回归4/5待022定位，训练短跑待完成）。优先级：P0。依赖：001；训练加载可先实现，最终资源短跑使用 004 的最小审计集。

## 当前进度

008a B0完整链路五例未接话，已按用户决定启动训练准备。独立conda prefix `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/envs/training`已建立，实测torch2.4.1+cu121、transformers4.46.3、peft0.13.2可导入；环境建立不等于真实参数更新或恢复验证。

001a记录发布布局，001d和008a证明推理路径strict恢复可运行；这些不替代训练加载审计、零更新数值对齐或optimizer/RNG恢复。`train_layer1.py`、训练配置和GPU短跑入口仍待实现，004已交付r5正式数据及最小审计集；最终短跑仍待训练器实现及017服务回归完成，实际步数/长度/batch未冻结。

已实现公共完整加载layer1_model.py、已有q/v LoRA精确白名单、独立官方Model零更新check_layer1_zero_update.py及单卡入口；现有模型服务复用公共加载。固定15个历史prompt、完整词表raw logits及权重前后摘要，详见[017](017_training_loader_zero_update.md)。2026-10-20的r4已通过完整权重恢复及零更新，15个prompt共111个生成步logits/IDs完全一致、前后摘要不变；服务回归136拍为4/5，第4例词事件分拍差异由[022](022_runtime_replay_boundary_ordering.md)定位，017仍不关闭。这些代码不实现optimizer或梯度更新，真权重对照及受影响001逐拍回归通过前不放行。

## 问题与目标

发布模型包含基础权重之外的控制 embedding/head 和 q/v LoRA。目标是先证明恢复正确、梯度范围正确、训练可运行，再承诺训练规模或工期。不能把“加载成功”视为恢复了完整官方 checkpoint。

## 继续训练的恢复契约

所有训练臂必须从发布的官方 DuplexCascade checkpoint 完整恢复，再开始本次继续训练；不能仅加载 Qwen2-7B-Instruct 后随机初始化双工参数。基础模型只是恢复依赖，tokenizer/新增 token、官方训练后的 embedding/lm_head、现有 q/v LoRA 及模型配置均须恢复。

继续更新已有 q/v LoRA，不额外叠加一个随机初始化 adapter 替代官方 adapter。首轮冻结基础模型及已恢复 embedding/head。发布资产若没有 optimizer/scheduler/RNG 状态，则本次新建并记录它们；这属于从官方模型权重继续训练，不能宣称逐步续接作者原训练。中断本次作业后的恢复则必须包含本次训练状态和数据生成/采样位置。

## 工作项

- [x] 盘点发布资产布局与 token 映射，完整恢复基础模型、embedding/head、LoRA 和推理配置；保持无 System Backchannel 的五类 token。
- [x] 在固定 prompt 上将训练加载路径的无更新输出与官方推理路径比较，记录 dtype/设备差异及容忍标准；保存前后权重摘要。
- [ ] 引用 001 冻结的独立官方参考资产、prompt/历史与容忍标准；本项验证训练加载路径，不代替 001 对 X-Talk 连续运行时的逐拍检查。发现共同参考或资产变化时同步重验受影响的对照。
- [ ] 首轮只开放既有 q/v LoRA，列出可训练参数名与数量，验证 embedding/head 和其他基础参数冻结；loss 仅覆盖符合监督规则的 assistant 位置。白名单已验证112张量/5046272参数；loss mask仍待训练器实现。
- [ ] 实现可复现的 optimizer、scheduler、随机种子、gradient accumulation、gradient checkpointing、保存/恢复；新增训练逻辑使用正常 Python 模块，不将模型生命周期复制成第二套产品服务。
- [ ] 准备独立远端 conda 环境与调度脚本，先一张 24GB 4090，以不同真实长度 batch 测峰值显存、step time、tokens/s、数据等待和保存开销。
- [ ] 发生 OOM 时先调整长度/batch/累积；需要多卡或分片时根据实测记录方案。上限 8×4090，不承诺单卡能容纳所有长度，不引用 H100 耗时作预算。

## 拟交付物

`scripts/training/train_layer1.py`、`configs/layer1_training.yaml`、`scripts/remote/run_layer1_training.sh` 及对应 docs。checkpoint、优化器状态和大日志留远端，仓库报告记录路径和摘要。

## 测试与完成条件

- [x] 输出完整权重加载审计：每类发布参数与目标参数对应，缺失、意外 key 和 shape 不一致均为零，或仅有预先登记且验证等价的映射；不允许静默跳过、随机填补或未说明的 strict=False。
- [x] 零更新推理使用相同 prompt IDs、精度、生成设置对照官方路径，验证 logits/贪心输出及控制行为；数值容忍在比较前冻结，差异越界阻断开训。
- [ ] checkpoint、base、tokenizer、embedding/head 和 LoRA 的来源摘要及恢复后摘要有记录；三训练臂起始可训练权重完全相同，只有原定 LoRA 参数参与更新。
- [ ] 有限步训练 loss/gradient 为有限值，仅允许参数改变，目标 mask 不含 user/padding，输出没有损坏协议。
- [ ] 使用 004 生成的合法 micro-turn 样本完成一次真实参数更新；保存/恢复覆盖权重、optimizer、scheduler、RNG 和数据生成/采样状态，与未中断短跑核对，明确非确定性来源。
- [ ] 回填 GPU/CPU/内存、最大序列长度、batch/累积、峰值显存、步耗时、预计总预算和退出码。
- [ ] 006 的两轮预算由短跑确定后冻结；本 issue 不运行完整三组训练。
