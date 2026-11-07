# 五场景数据试造

日期：2026-11-07。工作单：DCT-002—004。依据：[数据构造设计](../dev/layer1_training/data_construction.md)。

本轮试造五个独立任务来源，通过同来源分支覆盖交接、首音前／后取消、用户与系统附和、主动澄清、共享前缀、过期／晚到分析、递进回答、自我修正及失败恢复。分支不是新增独立来源，全部属于 `pilot` 分区，不参与正式训练或评测。

本轮采用人工编写的文本与模拟调度。没有音频、TTS 对齐、真实 SoulX／X2 回放、外部教师或独立审核；原始状态字段只是模拟观察，不是冻结权重预测。三类视图是可阅读、可检查的 SFT 语义样例，尚无模型专属 tokenizer 与 token 级标签，不可直接宣称为可训练语料。主动澄清单列未来协议，不新增现有五状态，也不绕过普通回答的 complete 边界。

后续 [Layer 2 周期设计](../dev/layer2/protocol.md)仅保留对话与上一轮 `analysis` 输入，每周期产生增量分析和三值进度，结束时另生成 `result`，仅将结果注入两个下游。本文记录的 pilot v1 仍含独立资料、旧状态与事件输入，只有分析正文目标，并按旧方式发布中间分析；尚未适配当前输入、进度和最终结果协议。本次保留原产物与模拟账本，不将旧轨迹宣称为新协议回放。

当前已确定不训练 Layer 2，其周期轨迹用于协议诊断、评测及构造两个下游的结果利用数据。既有 `layer2_sft.json` 保留为历史试造材料，不作为待训练语料；当前专项训练对象为 Layer 1 和后续适配的 SoulX-Duplug。

后续 [Layer 1 周期设计](../dev/layer1/protocol.md)采用持久 token Context，并为思考请求与系统附和设置专用 special token。现有 pilot 只记录语义输入和目标，尚未适配逐批 token 交错、词表或实际生成回写，不能将旧 JSON 字段视为已实现的模型输出协议。

## 场景与监督统计

| 来源 | 场景与关键对照 | 派生轨迹 |
| --- | --- | --- |
| scene01 | 翻译；普通交接、尾词晚提交、不确定停顿及重复 complete | 1 |
| scene02 | 会议提醒改日期；首音前与已播后取消恢复 | 2 |
| scene03 | 整理安排；系统／用户附和、重复抑制、避免错误赞同 | 1 |
| scene04 | 复试通知；共享前缀下自行补足、长篇相关、值得澄清、短篇转场、自行查找，以及晚到分析 | 5 |
| scene05 | 装箱；可靠递进、固定已播错误纠正、超时、执行失败 | 4 |

五个独立来源共 13 条轨迹，覆盖 45 个明确标签。分支复制的共享前缀保留一致监督；不作为新增独立来源。

| 视图 | 展开样本数 | 按输入／目标／协议范围去重 | 内容 |
| --- | --- | --- | --- |
| [SoulX-Duplug](../../datagen/pilot/soulx_sft.json) | 26 | 18 | 用户状态候选标签及单列的未来介入语义 |
| [Layer 1](../../datagen/pilot/layer1_sft.json) | 48 | 36 | 等待、请求思考、系统附和、普通回答、恢复及后续正文 |
| [Layer 2](../../datagen/pilot/layer2_sft.json) | 16 | 9 | 当前分析、信息缺口、增量结论及变化依据 |

没有思考调用的分支不虚构 Layer 2 样本；思考结束、失败和超时是运行时事实，不作为话轮动作或 Layer 2 正文监督。固定错误只在一条压力分支中出现，不作为正向表达目标。

## 阅读与复现

先看[逐场景中文审阅稿](../../datagen/pilot/review.md)，再查看[三视图与账本字段](pilot/README.md)。同一轨迹的三个模块按各自真实输入构造边界取样，时间不要求相同。

例如 scene05／progressive：SoulX 在 660ms 读到完整任务，候选状态为 `user_complete`；Layer 2 在 1280ms 读到任务与前次分析，继续检查组合；Layer 1 到 1680ms 读到已发布 v2 后，才监督补充“两件 A 和一件 B，20kg、80 元”。这是模拟时序的一致性示例，不是实测推理速度或 thinking 收益。

实现入口及对应说明：

- [场景源](../../datagen/scenarios.json)：[字段与来源说明](scenarios.md)。
- [导出器](../../datagen/build_pilot.py)：[核心函数与损失边界](build_pilot.md)。
- [受限运行脚本](../../datagen/run_remote_pilot.sh)：[运行参数与资源](run_remote_pilot.md)。
- [反例测试](../../tests/test_datagen_pilot.py)：[测试说明](../tests/test_datagen_pilot.md)。

本地使用已有 `interclarify-dev` conda；受限入口与远端相同，输出目录必须不存在：

```bash
bash datagen/run_remote_pilot.sh /path/to/conda-env /path/to/new-output
conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -p test_datagen_pilot.py -v
```

本地 17 项新增边界测试及 112 项完整回归通过。远端生成与 17 项边界测试均退出 0，五份主要产物及清单与本地 SHA256 一致；单 CPU、峰值 RSS 约 19.2 MiB，产物约 417 KiB。资源上限和实际路径见[远端记录](remote_validation.md)。DCT-002—004 均完成并归档；NTF-054 的正式复测保持独立。
