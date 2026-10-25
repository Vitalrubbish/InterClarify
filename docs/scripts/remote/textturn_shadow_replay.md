# TextTurn Nemotron影子回放

对应 `scripts/remote/textturn_shadow_replay.py`，属于TT-003/004。`replay_case`用80ms真实时钟发送固定合成用户语音，独立轮询有序ASR事件；每次转写先写SharedContext并由只读消费者读取，再消费160ms完成事件。EOF和排空内容单独记录，不冒充在线版本。

`ShadowState`仅模拟Listen/Speak、8 token/480ms生成和独立播放尾窗；唯一影子执行点接受start/stop，不触碰现役播放器或TTS。当前文本来自Context，控制专用末尾句读归一化仅生成副本。`LatestControlWorker`限制一个在途及一个待处理请求，合并时保留累计文字，HTTP耗时含排队与传输。

TT-007复用的`ShadowState`新增可选`control_ms`与`generation_ms`，默认均为480，既有入口行为不变。控制周期只决定连续no-voice计数单位；生成周期独立决定8 token片段发布、生成完成及播放完成的时间。160ms对照使用control=160、generation=480，播放尾仍为960ms，不把控制请求加密误当生成／播放加速。

评分保留四类及陈述句原计划分母。v2使用[因果trace评分器](../training/score_textturn_trace.md)：误动作、ASR未观察充分、运行错误分别记录；完整参考匹配仅作诊断，不产生语义让轮锚点。正常接话须有绑定当前输入的审核标注，否则明确未知。依据首次可见至返回≤1000ms才命中，调用本身必须已包含依据，窗口聚合等待不隐藏。所有步骤、Context版本、消费者读取和动作返回写trace，运行失败保留逐例原因。

来源为Kokoro合成语音，保持来源组独立但不声称自然人或未见模板泛化。端口均本机，真实模型只在远端单卡串行评估作业内运行；有音频但没有充足可对齐ASR证据时结论为证据不足。

附和必须有明确可判定的当前转写及Speak控制输入才算正确保持，不能因ASR漏掉附和而获得成功。无法观察为unknown，而非false_stop。关闭版本及消费者实际读取单独写trace；运行成功要求真实步骤和控制调用均存在且无错误。

停顿禁抢区间从不完整前缀ASR首次可见开始，持续到后续转写实际可见，而非音频已发送时刻；这样ASR滞后不会把仍然不完整的控制输入误算成已续说。输入内的合成静音时段和ASR可见区间分别保留。

trace的kind标记在线、EOF排空、Context或控制事件，原始ASR／生命周期事件种类另存source_kind，避免字段覆盖隐藏EOF区别。汇总同时列计划来源组与每类实际可观察来源组；任一类不足100组时，保留完整计划分母并记证据不足。

新回放不再执行v1的整段参考锚点评分；cases只保存运行事实，完整trace由v2统一产生summary.json及opportunities.csv。--annotations可显式提供盲审文件，审核hash和Context版本必须匹配；没有文件时不会自动给接话能力判通过。历史v1输出保留不改写，重评分使用新目录。
