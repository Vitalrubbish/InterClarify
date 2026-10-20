# 首轮训练与DuplexCascade公开训练设置对照

更新：2026-10-20。对应035；按用户要求不展开上下文窗口长度。结论：当前是从发布双工权重继续适配的受控实验，初始化、更新范围、训练目标和数据构造细节均有区别，不能称为仅缩小训练集的官方复现。没有修改任何训练配置或启动新任务。

## 依据与可信范围

官方依据为[论文3.3与4.1](https://arxiv.org/html/2603.09180v1#S4.SS1)、固定提交`42893024ca90c8de8ac3ed624467ebc123512ff8`的[model.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/model.py)、[server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py)及实际冻结checkpoint的train_cfg.json。2026-10-20重新检查官方当前main，树中仍只有推理、web及资源等11个文件，未见训练循环和完整数据生成器；公开model.py内容摘要与本地冻结版本相同。[线上核查记录](../reports/layer1_training/issue035-official-comparison-20261020/public_sources.json)

本项目以006已执行源码`c388a2f`、各臂真实manifest/summary、004的r5审计和当前代码交叉核对，不只读取最新YAML。[证据摘要](../reports/layer1_training/issue035-official-comparison-20261020/evidence.json)

论文记载的训练设计、发布模型结构元数据和推理代码是不同证据层级。发布train_cfg只有model部分：模型名、LoRA设置、gradient_checkpointing等，不包含完整优化器、数据管线或loss配置。

## 已确认的主要差异

| 项目 | 官方论文/发布依据 | 本轮实际执行 | 含义 |
| --- | --- | --- | --- |
| 初始化 | 从Qwen2-7B-Instruct适配双工协议 | 先完整恢复发布DuplexCascade，再更新其已有LoRA | 是继续适配，不是重新学习全部控制协议 |
| 可训练参数 | 论文更新q/v LoRA，以及完整原始/新增token embedding与输出head | 仅更新原112个q/v LoRA张量，embedding/head及副本冻结 | 更新自由度更小；也不自动保证能力不退化 |
| 损失 | 论文控制类别权重：speaking1、finish10、interruption5、backchannel2、thinking1；普通版无system-backchannel | Transformers普通token交叉熵，所有有效监督token同权 | 重点控制类别未获额外权重；见下文公开代码歧义 |
| 学习率 | 论文AdamW，1e-5 | AdamW，2e-5 | 峰值是论文的两倍，不宜仅因参数少就假定更新一定保守 |
| batch | 论文报告batch32，未公开设备batch/累积拆分 | 每设备1、单GPU、累积2，有效序列batch2 | 梯度估计与更新噪声不同；不将论文32擅自解释为每卡32 |
| 优化器步数 | 论文5,000步 | 每臂1,214步 | 原始对话数、编码序列数和更新步数须分别比较 |
| warmup与退火 | 论文明确warmup500步，占5,000步的10%；该段未说明其后完整曲线 | warmup37步，约3.05%，随后线性降至0 | 不只是总步数等比例缩短；不宣称作者同样线性衰减 |
| 原始数据 | 论文随机抽UltraChat 50k，精确ID未公开 | 从固定shard字节窗口读取6,000条原始记录，过滤/排除/去重后选1,000条train；另200dev/300test未训练 | 不同抽样方法和来源覆盖，且实际是1k而非10k |
| 曝光安排 | 论文未给出原始对话到序列/epoch的完整对应 | 单epoch，2,428序列/臂、1,193,875监督token，所有train对话曝光一次 | 不能用50k与1k比例直接推算官方epoch或更新强度 |
| 用户表面形式 | 论文未登记本项目这类数值口语化及句读三臂设计 | 用户数值先转确定性英文读法；T1保留句读、T2去普通句读、T3按对话500/500；assistant正文不变 | T1“原样”也是共同数值前处理后的原样 |

上述官方训练超参与可训练范围来自[论文4.1](https://arxiv.org/html/2603.09180v1#S4.SS1)；本轮参数见[正式配置](../configs/layer1_adaptation_training.yaml)、[实际完成manifest](../reports/layer1_training/issue006-round1-20261020/completion.json)和[layer1_model.py](../scripts/training/layer1_model.py)。

## 需要纠正的loss口径

论文明确写类别加权；但公开model.py的forward第99–103行使用普通`nn.CrossEntropyLoss()`，没有传类别权重；文件自称inference-oriented wrapper，完整训练器并未公开。[固定官方代码](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/model.py#L99)

因此，准确说法是：**本轮与论文描述的加权训练目标不同；公开仓库不足以复现或验证作者实际训练loss的全部细节。** 不能反过来推断作者没有使用加权，也不能说我们使用普通CE就已经与官方实际训练一致。此前关于“官方加权”的表述须理解为论文声明，不是已经从公开训练循环独立验证。

本轮代码中的weighted_loss只是把两个micro-batch按有效监督token数合并，梯度相当于整个累积批次的普通token平均，并不是按控制类别加权。用户/header/历史mask为-100，正文、控制和EOS均参与目标。作者训练loss的权重归一化分母、是否只加权控制位置、普通正文/EOS细节及跨设备归约均未完整公开，不能推断。

## 数据与事件构造的细节

论文的随机用户1–7 token、assistant正文10 token、自然停顿概率0.10/1–5拍、插话概率0.30、用户附和概率0.01及回答后thinking1–20拍，在本项目都有对应实现；不是完全不同的数据范式。[论文3.3](https://arxiv.org/html/2603.09180v1#S3.SS3)

但对应参数不意味着采样过程相同：

| 项目 | 本项目明确的行为 | 与公开描述的关系 |
| --- | --- | --- |
| 用户切分 | 按原始字符offset保留文本；多token共享字符时延长边界；标点独占片段先合入邻片段，避免去句读后成为no-voice | 对论文严格随机1–7 token存在例外；r5全部1,500条记录286个超7片段，非仅1,000条train统计 |
| assistant切分 | 每片最多10个正文token，末片可不足10个；控制及EOS另计 | 基本符合论文意图，不能把“10正文token”当整个micro-turn总长10 |
| 停顿 | 仅非末用户片段后抽0.10，插入1–5个no-voice/talking拍 | 论文写每个用户micro-turn后；我们限定非末边界，避免最后片段之后再监督等待 |
| 插话 | 仅存在后续用户轮且旧回答至少2片时抽0.30，边界位于回答结束前；优先消费下一用户轮，丢弃旧回答尾部 | 条件分母比论文“每个系统长轮”表述窄，不能称总体插话比例相同 |
| 用户附和 | 只在首回答片之后的实际续写拍抽0.01；首片和插话拍不抽，词表固定为yes/okay/right/I see | 分母/互斥规则比论文“系统说话中每micro-turn”更具体，作者边界代码未公开 |
| 事件计划 | r5先固定epoch0事件与分拍，再派生三种句读视图，同一事件只监督一次 | 论文称动态构建，但未公开重采样时机；不能断言作者每步或每epoch重采样 |
| 混合增强 | 按原始对话严格50/50，增强不翻倍曝光，三臂共用事件/监督目标 | 本项目实验设计，论文未登记同样的句读三臂 |

实现见[layer1_data.py](../scripts/training/layer1_data.py)、[同路径说明](scripts/training/layer1_data.md)和[019审计](duplex_data_alignment_audit.md)。上述偏离可能改变等待/接话样本比例和上下文分布，但没有证据证明其中某一项就是持续talking的唯一原因。

## 对齐项与无法确认项

已对齐：Qwen2-7B-Instruct模型家族、发布tokenizer和既有控制ID、普通版无系统附和、文本next-token监督且只监督assistant、q/v LoRA结构、r16/alpha32，以及AdamW优化器家族。发布train_cfg还确认dropout0.05、bias none、gradient_checkpointing true，本项目保持这些设置。`freeze_llm:true`不能单独解读为embedding/head也冻结：发布结构明确有modules_to_save，论文另述它们参与训练。[官方Model结构](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/model.py#L59)

我们明确采用weight_decay0.01、betas0.9/0.999、eps1e-8、梯度裁剪1.0、BF16、非重入gradient checkpointing、确定性计算；作者的相同细节未在已核对资料中完整给出，不能填写成已确认差异。官方使用8×H100、本轮单4090，是工程资源差异，不能直接当作效果差异原因。

我们不跨对话packing，按完整事件分窗并重叠带入历史，历史重复部分不再监督；作者的packing、padding、历史重叠、mask及采样器细节未公开。不能因我们采取了这些做法，就断言作者采取相反做法。

## 训练方式与部署差异分开

官方推理消费Kyutai Word逐词strip后每拍空格连接、首个非空词后起拍；当前链路使用Nemotron字符前缀增量及会话起拍，TTS也替换为Kokoro。它们改变实际输入分布和响应时间，但不是训练优化器差异。[固定官方server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422)

两边的训练都是从文本构造双工序列；我们只做数值/句读等模拟，尚未完整模拟Nemotron的词错误、迟到、残词或实际发射节奏。这个覆盖不足不能表述成“官方用真实ASR训练、我们没有”。600ms是运行节拍，本轮合成事件没有真实音频到达时钟。

## 对下一步的影响

优先复核训练目标和控制类别的重要性，其次评估冻结embedding/head的限制及数据边界与真实前缀分布。不能将本轮失败简化为上下文短、数据少或未使用加权中的单一原因。若开展加权对照，应保持其余变量固定；若同时解冻embedding/head或从Qwen2重新初始化，就必须作为另一条件登记，不能把收益全部归于加权。

该报告纠正的是证据与归因范围，不修改既有首轮结果；035仅交付调研，后续训练变更另行实施。
