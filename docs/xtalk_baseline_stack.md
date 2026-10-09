# 第一套 X-Talk 组件组合与冻结门禁

## 1. 当前决策与状态

先跑通原生组合并记录基线，再开始 `feature/duplex-control` 上的控制层改造。当前为**候选组合，尚未运行冻结**；模型权重 revision、服务提交和资源占用均待核验。InterClarify 的 P0 环境检查不能替代该组合的验收。

改造目标采用 DuplexCascade 无 System Backchannel 版本；Layer 0 当前移除，System Backchannel 始终关闭。用户附和识别、有效插话停播、持续监听、等待与回答仍属于目标能力。论文命名依据见[第 4.1 节](https://arxiv.org/html/2603.09180v1#S4.SS1)。

## 2. 第一套候选

| 组件 | 候选实现与模型 | 选择依据与需固定的信息 |
| --- | --- | --- |
| X-Talk | `Vitalrubbish/xtalk`，起点 `5f0d9959edf1026588246efbed827b078cbb114c` | 原生 `DefaultService` / `DefaultAgent`；改造前保存源码提交和配置摘要 |
| ASR | `SherpaOnnxASR` + INT8 SenseVoice Small，`mode=offline` | 沿用上游演示的模型类型；固定 ONNX 文件校验值、服务提交和 mock window 参数 |
| LLM | `DefaultAgent` + 本地 vLLM；`cpatonn/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` | 固定提交的本地部署示例给出该模型；核验权重 revision、量化来源、上下文上限和生成参数 |
| TTS | `IndexTTS` 1.5，本地服务 | 沿用上游演示；固定服务提交、权重、分句/生成参数和一份中文参考音色及校验值 |
| turn detector | `XTurnix` + XTurnix-ZH Base 0.6B，本地 vLLM | 已有适配器，提供 listening 下的 keep/start 与 speaking 下的 keep/stop；固定权重 revision、服务名 `xturnix`、上下文和超时 |
| VAD | 原生浏览器 VAD，额外服务端 VAD 默认不加载 | 固定前端版本、模型和阈值；headless 回放须提供并记录等效 speech start/end 事件 |
| 系统附和 | `backchannel_model=null`，`backchannel_source_dir=null` | 原生 Agent 的 partial 分支仍更新历史，但不调用附和模型或产生附和音频 |

ASR、LLM、TTS 选择接近 [X-Talk 上游演示](https://github.com/xcc-zach/xtalk#online-demo)，LLM 的具体候选来自固定 checkout 的 `docs/tutorial/sample_config_for_fully_local_deployment.zh.md`。选择 [XTurnix](https://github.com/xcc-zach/xturnix) 是因为它同时提供开始回答与停止说话决策，适合本次语义双工控制审计；这项选择仍需原生交互测试支持，不把其 keep/stop 分类预先当作已验证的用户附和能力。基线阶段不同时比较 TurnSense 与 XTurnix，避免增加变量。

## 3. 能力与实现差异

- SenseVoice 此处为离线模型配合 `MockStreamRecognizer` 的增量模拟；保存真实到达的 partial 与修订，不能声称原生 streaming ASR。短窗口开销、前缀稳定性和 partial 到达间隔是冻结门禁。
- IndexTTS 1.5 需实测分段生成、首音频到达和取消响应；增量文本分句不自动等于模型原生流式 TTS。
- 原生基线保留其 VAD 和 ASR gating 条件。当前声明行为对齐，不声明完成论文 VAD-free 架构；未来若移除 VAD，先另行更新方案并保留独立基线。
- XTurnix 是独立的轮次检测模型，Qwen3 负责回答。本组合不等同于论文中控制 token 与回答共用一个经适配的 LLM。
- 不预先承诺单张 24 GB GPU 容纳全部模型。集群先把回答 LLM 与语音/轮次服务分开部署，再根据实测调整；不把 8 张 4090 的显存视为统一地址空间。

如果候选组合不能通过门禁，先记录失败原因和组件变更，再重跑原生基线；不得一边更换底层模型一边修改控制策略。

## 4. A0 执行顺序

1. 在本地与远端分别用 conda 创建独立 X-Talk 开发环境；vLLM、ASR 与 TTS 服务按依赖兼容性使用独立 conda 环境，保存显式依赖记录。
2. 在固定 checkout 上运行上游测试；核验 optional extras、权重可用性与来源，保存实际服务提交和模型 revision。
3. 启动原生服务，用固定音色、模型和 VAD 配置完成音频输入、识别、回答、TTS 与播放闭环。显式关闭系统附和配置。
4. 在远端集群保存停顿、句末回答、用户短附和、有效插话、连续对话的基线轨迹，记录首 partial、首 token、首音频、停播延迟、队列积压和各服务峰值显存。
5. 固定 FDB 数据、适配器与判分版本，运行原生 smoke；用户附和抗误打断保留，系统附和生成指标标为当前范围外。阻塞时保存具体原因，不将该项报告为通过。
6. 保存组件锁定记录，核验后冻结组合；才进入改造计划的 A1。集群执行前另建任务单与对应脚本。

## 5. 冻结产物与验收

组件锁定记录至少包含：X-Talk 提交、模型 ID/revision、权重校验值、量化类型、服务提交、Python/CUDA/推理依赖、GPU 分配、VAD 配置、ASR 模式和参数、TTS 音色与参数、提示词与生成参数、配置摘要及运行证据路径。

冻结需要同时满足：原生上游测试与音频闭环 smoke 通过；来源和配置字段完整；首包延迟、实时吞吐、停播与资源证据可追溯；已明确 ASR/TTS 的流式能力限制及基线行为缺口。FDB 的通过或具体阻塞原因单独登记。

首轮基线用于设定延迟预算，预算须在开始改造前写定。后续原生、无 System Backchannel 改造版和 InterClarify 共用同一冻结组合；组件变更建立新的基线记录。
