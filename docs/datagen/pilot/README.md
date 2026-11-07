# `datagen/pilot` 产物说明

该目录对应实际生成的语义试造产物，各文件均无实现类或方法。所有来源属于 `pilot`，原始音频及真实前端回放尚未生成；目标待独立审核，全部 `eligible_for_training=false`。

| 文件 | 整体作用与核心字段 |
| --- | --- |
| `soulx_sft.json` | 控制器的可见音频占位、文本、运行事实及未来分析条件；候选 `user_state`，未来介入语义另列；输入不含本帧原始预测 |
| `layer1_sft.json` | 转写、原始状态、有效 complete、生成历史、取消／播放事实和实际注入分析；目标为等待、请求思考、表达与后续正文 |
| `layer2_sft.json` | 每次短推理实际读到的前缀、前次分析与新增观察；目标只有分析正文，不包括话轮指令或生命周期 |
| `trajectories.json` | 来源共享前缀展开后的完整事件与决策，含隐藏剧本及精确播放审计；禁止整份拼入模型输入 |
| `manifest.json` | 五来源／分支／样本／去重监督数、分来源统计、覆盖标签、源文件及产物 SHA256；跨机器可重现 |
| `execution.json` | 单次执行的真实机器、conda prefix、Python、耗时、内存及资源限制；不同机器正常不同，不纳入跨机器产物一致性比较 |
| `review.md` | 13 条派生轨迹逐事件中文时间线，以及三个模块的输入边界、监督目标和理由 |

三份视图都包含 `input`、`target`、`messages`、`loss_boundary`、`training_blockers` 和 `audit`。`messages` 是通用语义包装：前两条条件消息损失为零，最后一条候选目标损失为一；不确定控制标签为零。`audit` 不进入模型提示。原始状态、候选标签与未来控制判断各有来源边界；固定错误只作为历史条件。

后续 [Layer 2 周期设计](../../dev/layer2/protocol.md)采用冻结模型与提示词，不训练 Layer 2；每周期记录增量分析和三值进度，仅在正常结束时发布 `result`。本目录保留 pilot v1 原始正文目标、旧发布方式及实测摘要，`layer2_sft.json` 仅作历史诊断材料，不作为待训练语料，也不代表已经适配当前协议。

当前 `messages` 不是已冻结的 Qwen 或 SoulX 输入格式。没有 tokenizer 级 `labels`、真实音频 token 或现役主动澄清接口，不可直接交给正式训练器。可首先通过[逐场景审阅稿](../../../datagen/pilot/review.md)检查监督内容，再查 JSON 的完整输入。
