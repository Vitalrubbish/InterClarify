# Issue 005：恢复训练状态并完成远端资源短跑

状态：待办。优先级：P0。依赖：001；训练加载可先实现，最终资源短跑使用 004 的最小审计集。

## 问题与目标

发布模型包含基础权重之外的控制 embedding/head 和 q/v LoRA。目标是先证明恢复正确、梯度范围正确、训练可运行，再承诺训练规模或工期。不能把“加载成功”视为恢复了完整官方 checkpoint。

## 工作项

- [ ] 盘点发布资产布局与 token 映射，完整恢复基础模型、embedding/head、LoRA 和推理配置；保持无 System Backchannel 的五类 token。
- [ ] 在固定 prompt 上将训练加载路径的无更新输出与官方推理路径比较，记录 dtype/设备差异及容忍标准；保存前后权重摘要。
- [ ] 首轮只开放既有 q/v LoRA，列出可训练参数名与数量，验证 embedding/head 和其他基础参数冻结；loss 仅覆盖符合监督规则的 assistant 位置。
- [ ] 实现可复现的 optimizer、scheduler、随机种子、gradient accumulation、gradient checkpointing、保存/恢复；新增训练逻辑使用正常 Python 模块，不将模型生命周期复制成第二套产品服务。
- [ ] 准备独立远端 conda 环境与调度脚本，先一张 24GB 4090，以不同真实长度 batch 测峰值显存、step time、tokens/s、数据等待和保存开销。
- [ ] 发生 OOM 时先调整长度/batch/累积；需要多卡或分片时根据实测记录方案。上限 8×4090，不承诺单卡能容纳所有长度，不引用 H100 耗时作预算。

## 拟交付物

`scripts/training/train_layer1.py`、`configs/layer1_training.yaml`、`scripts/remote/run_layer1_training.sh` 及对应 docs。checkpoint、优化器状态和大日志留远端，仓库报告记录路径和摘要。

## 测试与完成条件

- [ ] 固定样本未更新推理与官方路径一致或差异有可接受解释；实际 prompt IDs 与生成历史不变形。
- [ ] 有限步训练 loss/gradient 为有限值，仅允许参数改变，目标 mask 不含 user/padding，输出没有损坏协议。
- [ ] 保存/恢复可继续训练，并在相同设置下与未中断短跑核对，明确非确定性来源。
- [ ] 回填 GPU/CPU/内存、最大序列长度、batch/累积、峰值显存、步耗时、预计总预算和退出码。
- [ ] 006 的两轮预算由短跑确定后冻结；本 issue 不运行完整三组训练。
