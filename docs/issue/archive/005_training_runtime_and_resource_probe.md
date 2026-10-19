# Issue 005：恢复训练状态并完成远端资源短跑

状态：完成，已归档。2026-10-20用户授权启动32/100条短跑，r1已完成；实现`c21a352`，资源余量修正及恢复证据`7326b6e`，作业`job-179242817730774595080-xuan-zhang`。017已关闭，004使用r5审计数据。

本次执行拆为[024训练状态实现](024_layer1_training_state.md)和[025远端试跑](025_layer1_remote_probe.md)，均已完成。先32条真实更新及独立进程恢复，再100条多长度资源测量；从完整官方权重出发，只更新已有q/v LoRA。正式首轮每臂1,000条、1epoch，有条件第二轮最多3,000条，均不在005执行。32/100指原始对话池，有限步实际曝光数见报告。两份总设计文档为用户工作区删除状态；本次核对其HEAD版本，保留用户改动。

## 当前进度

008a B0完整链路五例未接话，已按用户决定启动训练准备。独立conda prefix `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/envs/training`已建立，实测torch2.4.1+cu121、transformers4.46.3、peft0.13.2可导入；环境建立不等于真实参数更新或恢复验证。

训练器、短跑配置、状态保存恢复和单卡入口已交付。32条池连续4步与2步中断后恢复至4步，LoRA/optimizer/scheduler/RNG/游标/后续loss/协议输出全部精确一致。100条池256/512/1024/2048更新通过，4096首步OOM；按实际显存保留至少2GiB余量选择512、batch1/累积2。完整1,000条三臂各11,526序列、1,193,875监督token、单epoch5,763步；约0.93GPU小时/臂为外推，保留8小时上限。第二轮3,000条尚未构建，仅估计约2.84GPU小时/臂并保留16小时上限。

公共加载与服务复用同一路径。固定15个历史prompt、完整词表raw logits及权重摘要见[017验收报告](../../../reports/layer1_training/issue017-loading-20261019/README.md)：111个生成步logits/IDs完全一致；136拍服务回归第4例约1.59ms拍界差异经用户接受为抖动，017已关闭。真实训练及资源证据见[005报告](../../../reports/layer1_training/issue005-probe-20261020/README.md)。005仅放行恢复和资源门禁；007开训前准备仍未完成，尚不放行006。

## 问题与目标

发布模型包含基础权重之外的控制 embedding/head 和 q/v LoRA。目标是先证明恢复正确、梯度范围正确、训练可运行，再承诺训练规模或工期。不能把“加载成功”视为恢复了完整官方 checkpoint。

## 继续训练的恢复契约

所有训练臂必须从发布的官方 DuplexCascade checkpoint 完整恢复，再开始本次继续训练；不能仅加载 Qwen2-7B-Instruct 后随机初始化双工参数。基础模型只是恢复依赖，tokenizer/新增 token、官方训练后的 embedding/lm_head、现有 q/v LoRA 及模型配置均须恢复。

继续更新已有 q/v LoRA，不额外叠加一个随机初始化 adapter 替代官方 adapter。首轮冻结基础模型及已恢复 embedding/head。发布资产若没有 optimizer/scheduler/RNG 状态，则本次新建并记录它们；这属于从官方模型权重继续训练，不能宣称逐步续接作者原训练。中断本次作业后的恢复则必须包含本次训练状态和数据生成/采样位置。

## 工作项

- [x] 盘点发布资产布局与 token 映射，完整恢复基础模型、embedding/head、LoRA 和推理配置；保持无 System Backchannel 的五类 token。
- [x] 在固定 prompt 上将训练加载路径的无更新输出与官方推理路径比较，记录 dtype/设备差异及容忍标准；保存前后权重摘要。
- [x] 引用 001 冻结的独立官方参考资产、prompt/历史与容忍标准；017报告及配置引用独立官方资产和15个历史prompt；训练路径不代替001逐拍检查，资产无变化。
- [x] 首轮只开放既有 q/v LoRA，112张量/5046272参数；真实更新前后完整摘要证明其他参数冻结，mask契约测试及训练数据逐span检查通过。
- [x] 实现可复现的 optimizer、scheduler、随机种子、gradient accumulation、gradient checkpointing、保存/恢复；新增逻辑为正常Python模块，独立进程恢复逐项精确一致。
- [x] 独立远端conda、1×24GB4090完成五档长度测量，GPU/CPU/RSS/步耗时/吞吐/等待/保存开销均有原件。
- [x] 4096 OOM保留，选用有实际显存余量的512窗口，未引入多卡/分片；不引用H100预算。

## 交付物

`scripts/training/train_layer1.py`、`configs/layer1_training.yaml`、`scripts/remote/run_layer1_training.sh` 及对应 docs。checkpoint、优化器状态和大日志留远端，仓库报告记录路径和摘要。

## 测试与完成条件

- [x] 输出完整权重加载审计：每类发布参数与目标参数对应，缺失、意外 key 和 shape 不一致均为零，或仅有预先登记且验证等价的映射；不允许静默跳过、随机填补或未说明的 strict=False。
- [x] 零更新推理使用相同 prompt IDs、精度、生成设置对照官方路径，验证 logits/贪心输出及控制行为；数值容忍在比较前冻结，差异越界阻断开训。
- [x] 全部资产逐文件摘要及恢复后完整模型摘要保留，七次独立恢复起始摘要相同；公共加载器不接收训练臂条件，三正式臂复用并须在各run再次核验。只有既有LoRA参与更新。
- [x] 有限步训练 loss/gradient 为有限值，仅允许参数改变，目标 mask 不含 user/padding，单片段输出协议检查通过；不代表控制质量验收。
- [x] 使用004的r5合法micro-turn完成真实参数更新，保存恢复覆盖权重、optimizer、scheduler、Python/NumPy/CPU/CUDA RNG及固定计划/采样顺序/游标；连续4步与2步中断后恢复至4步全部精确一致。
- [x] 回填1GPU/8CPU/32GiB、窗口512、batch1/累积2、峰值/步耗时/预计预算和整体退出0；总阶段约18.4分钟，输出约408MiB。
- [x] 006首轮精确步数和两轮GPU小时上限已冻结；第二轮未构建、精确步数仍为空，不伪造实测。未运行完整三组训练。
