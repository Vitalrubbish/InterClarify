# DuplexOmni 阅读报告

下文保留早期阅读与数据构造讨论；当前模块分工和训练范围以末节及 [Layer 2 周期协议](../layer2/protocol.md)为准。

## 框架设计

DuplexOmni在实现的工程框架和目前暂定的方案非常类似；

它的工作流程：

1. 每480ms一个周期
2. 每个周期 Thinker 负责接受当前周期的音频，结合之前 user 和 assitant 的文本历史预测当前周期 assistant 的输出，以及是否驱动/暂停 Thinking Layer 工作；
3. Talker 由当前的 output text token 生成 audio token，并且将 audio token 也加入到 talker 的 context 当中

与本项目协议相关的区别：[DuplexOmni 第 3.1 节](https://arxiv.org/html/2606.09186v1)将 Thinking Layer 描述为可插拔的外部 LLM 或 Agent，由交互层发出上下文请求，并流式返回中间结果。本项目明确在每次串行短推理边界重读最新对话，单次调用仍使用固定输入；只向下游提供正常结束时的 `result`。这些实时输入和发布规则采用本项目合同，不从论文描述推定可向在途调用追加输入。

对于我们框架设计的指导：

1. DuplexOmni 是 Thinker-Talker 架构，它的 Thinker 是 Qwen3-Omni，参数量高达 35B，Thinker 的输出是 json 格式化文本；我们的LLM不可能要求这么大的参数量，因此我觉得输出只要按照特定的方式编排即可，没有必要强制要求输出 json；

## 训练数据构造

DuplexOmni 训练数据的构造方法

1. Senario Seed + Content
2. Writer 负责用自然语言描述内容的组织
3. Director 负责将它们编排为具体的内容，并搭配上special token；
4. 最后再由 TTS 编排为音频（可能需要对齐）
5. 训练 Thinker 时用到的 CoT 是由 Director 根据 assistant 的回答反推得到

我们的训练数据构造方案：

1. 我们训练数据（文本/音频）的生成管线可以参考 DuplexOmni，先合成整段文本和音频；
2. 我们需要基于SoulX-Duplug和X2StreamingASR的输出pattern，对文本按窗口进行切分（如果时间/算力允许，甚至可以让这批训练数据过一遍ASR Frontend，得到最准确的结果）；
3. 思考请求与外部结果分别保留来源边界，具体编码待实现确定；不直接沿用 `[WAIT]` 取消思考。任务等待、结束和播放取消遵循本项目周期协议，不能由参考方法的 token 名称推导执行行为。

## 当前项目取舍

2026-11-07 用户明确将 Layer 2 收敛为冻结的外部思考层，通过提示词读取当前对话与上一轮分析，产生增量 `analysis` 和 `progress`，正常结束时另生成 `result`；只将最终结果注入 SoulX-Duplug 和 Layer 1，不训练或适配 Layer 2 参数。

该定位借鉴可插拔 Thinking Layer 的职责分工。DuplexOmni 模型内部的 Thinker 属于交互模型，本文的 Layer 2 对应外接 Thinking Layer，两者训练范围不能仅按名称类比。当前专项训练集中于 Layer 1 的请求、结果利用与表达，以及 SoulX 的结果条件化判断。

“实时对话”指每周期可见的用户转写和助手实际生成文本，仍不包含 SoulX 状态或播放状态；周期运行时、模型选型与提示词效果尚待实施和验证。
