# DuplexOmni 阅读报告

## 框架设计

DuplexOmni在实现的工程框架和目前暂定的方案非常类似；

它的工作流程：

1. 每480ms一个周期
2. 每个周期 Thinker 负责接受当前周期的音频，结合之前 user 和 assitant 的文本历史预测当前周期 assistant 的输出，以及是否驱动/暂停 Thinking Layer 工作；
3. Talker 由当前的 output text token 生成 audio token，并且将 audio token 也加入到 talker 的 context 当中

我们目前的实现和DuplexOmni的差异：在 Thinking Module 的设置上，DuplexOmni 是触发调用 Thinking Module (Thinking Layer) 之后，就不会去接收推理过程中新的输入信息了；这样的策略或许可以让系统处理复杂问题的能力，但是缺少实时的上下文信息，让系统难以去处理主动打断等交互强相关的问题；

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
3. special token 设置：类似于 DuplexOmni 设置 [THINK][WAIT]，分别对应启动和取消Thinking Module的思维；Thinking Module的返回结果需要用特殊的标识符进行封装，以和用户的输入token和模型的输出token做区分；

## 目前的疑惑

1. Layer 1 和 SoulX-Duplug 肯定需要重新训练，但是在我们目前的设计下 Layer 2 是否需要训练；如果需要，训练数据应该怎么构造？