# 工程实施计划

更新：2026-10-23。当前方案为 **Nemotron EN160 流式 ASR＋XTurnix 话轮控制**。本次将前端与控制分离：Nemotron 提供转写，XTurnix 根据转写历史和系统 Listen/Speak 状态预测动作。调整原因是此前前端方案已回退，现按用户决定验证 XTurnix 与现役 ASR 的组合。本文更新计划，不表示新链路已经部署或通过验收。

研究背景和范围见[研究主文档](research_design.md)，模块合同见[架构设计](research_design/architecture.md)。本轮已按用户指令拆分为 [XTX-001—006](issue/XTurnix/README.md)；XTX-001 已完成 FLEURS 输入与历史 ASR 基线冻结；XTX-002 已完成隔离环境、模型与协议冻结及 dev 验证；XTX-003 已完成真实时钟回放器与模拟契约验证；XTX-004—006 待实施，尚未提交正式回放或质量测试作业。

## 1. 当前步骤与边界

当前先进行 FLEURS 英文子集的两组件质量测试：真实音频流经 Nemotron，再把在线转写交给 XTurnix，测量最后一个词汇 token 可见到首次有效 `<|start|>` 返回的时间。将该增量与历史 Nemotron 延迟结合，给出音频到控制动作的链路估计。详细定义、分母和限制见[质量测试计划](dev/XTurnix/quality_test_on_fleurs.md)。

本轮不运行 Layer 1、Layer 2、TTS 或播放，不训练话轮控制器或 Layer 0，也不恢复此前取消的 FDB 测试。FLEURS 的末端 start 输出率不称为 FDB TOR，也不代表真实对话的话轮控制准确率。

后续完整链路继续保持单一仲裁器和单一 TTS 播放所有权。控制 token、thinking 请求与 CoT 均不进入 TTS；已听内容不可撤销。不设计 Layer 3。按用户确认的分工，Layer 2 只向上下文发布 CoT，不生成话轮建议或候选表达文本；话轮决策全部交给 XTurnix，Layer 1 负责措辞。此调整只同步研究合同，不变更本轮两组件测试范围或启动训练。

## 2. 现役底座与目标分工

现役配置为 X-Talk `ca9b23c134b390107601bc98954ab16276d86db9`、Nemotron EN160、Kokoro `af_heart`、600ms micro-turn、300/1200ms TTS 分段和会话 KV 复用，见[运行配置](runtime_baseline.md)。现役控制仍由 DuplexCascade 路径执行；采用 XTurnix 是目标方案，不冒称已完成替换。

| 模块 | 职责 | 输出或动作 |
| --- | --- | --- |
| Nemotron ASR | 接收持续音频并交付真实增量，保留生命周期与版本 | 累计文本、delta、观察截止点和接收时间 |
| XTurnix 控制策略 | 结合对话历史与当前 Listen/Speak 状态判断保持或转移；后续训练读取 CoT 并独立权衡介入 | Listen 下 keep/start；Speak 下 keep/stop，及合法动作分数 |
| Layer 0（后续） | 只预测系统简短附和时机 | 发出附和或继续等待，不预测通用话轮类别 |
| Layer 1（后续适配） | 请求思考，利用上下文生成澄清、回答或口头纠正 | 待表达文本与 thinking 请求 |
| Layer 2（后续接入） | 分析事实、缺口和条件依赖，求解任务并更新推导 | 只发布 CoT 至上下文，不提供话轮建议 |
| 统一仲裁器 | 结合控制策略、Layer 0/1 结果及实际播放状态执行 | 唯一的提交、等待与停止路径 |
| TTS 与播放器 | 合成并播放已提交表达，回传真实播放状态 | 用户可听音频 |

XTurnix 不替代 ASR，不输出上一方案的 idle、complete、backchannel 等用户状态类别。其 speaking/keep 表示此时继续说，不等于给出了独立的“用户附和”标签。控制动作与用户语义类别分开记录，不强造一一映射。

## 3. Nemotron 与 XTurnix 接口

### 3.1 在线输入和动作

Nemotron 固定 EN 0.6B、160ms 配置；传输使用真实时钟 80ms 音频包。保留原始文本、token/delta、会话 UUID、前缀版本与可见时间，暂停不结束 ASR，会话真正结束后的排空另列。

XTurnix 首轮使用 `xcczach/xturnix-pt`，冻结权重 revision、tokenizer、官方推理管线与依赖版本。中文微调变体不混入同一汇总；如需比较，另行冻结为独立配置。按状态只允许两个合法动作，取分数最高的动作作为原版基线，不在正式测试上调整 start 阈值。

按[官方推理管线](https://huggingface.co/xcczach/xturnix-pt/blob/main/turn_pipeline.py)移除最后一条用户消息的末尾 Unicode 标点和相邻末尾空白，保留内部标点、大小写及原始 ASR 记录；不能人工补句号。模型只看当时可见前缀，不读取参考转写或未来音频。

ASR 更新与真实的停顿事件可以触发判断。`<|pause|>` 必须来自因果可获得的音频停顿或真实上游分段事件，不能由录音 EOF 或离线认定的最后 token 注入；停顿检测器与阈值在回放前冻结，并记入延迟。单会话最多一个在途控制请求，后续观察有界缓冲，不无限并行。具体触发与末端评分见质量测试计划。

### 3.2 单一执行路径与状态同步

当前两组件测试只记录动作，不执行 `start` 或停播。完整系统接入时，XTurnix 输出属于决策，实际生成、提交和可听播放属于不同事件；状态由统一运行时依据实际会话及播放状态维护，不能在收到 Layer 2 结果时假装已经开口。

原 `TurnDetectorManager/TurnTakingManager` 与双工适配器不得同时执行开始/停止动作。新控制模式接入同一仲裁路径，旧 DuplexCascade 控制 token 保留真实生成历史但不重复执行。音频暂停、用户让轮、生成启动和实际开始播放分别记账。

文本持续送入表达上下文，不因尚未预测 start 而阻塞 thinking 请求；结果也不能反向改写已生成或已播放的历史。

## 4. Thinking 条件化控制的后续训练

原版 XTurnix 的 Listen/start 主要针对用户已让轮的情况；我们的主动介入还需要在用户持有话轮时判断是否值得开口。后续控制器应读取明确标识的已发布 CoT、最新用户输入、观察截止点/版本及实际播放状态，独立学习何时 keep、何时 start；用户打断系统仍由 Speak 下的 keep/stop 处理。CoT 发布只更新 Context，在下一独立控制周期读取，不额外触发一次 XTurnix，也不自动切换为 Speak。

Layer 2 只发布任务分析 CoT，不输出“继续倾听”“建议澄清”、介入意图或开口就绪字段；全部话轮价值与时机判断由 XTurnix 负责，Layer 1 负责表达。任务标识、发布版本、观察截止点与思考任务生命周期作为运行时元数据另记，不作为话轮建议；不新增独立的任务语义否决层。用户正在自行补充、分析已经过期或本来无需介入时，要保留 keep；已经说话时获得新 CoT，不因此启动第二路播放。

官方管线要求固定状态提示词及 user/assistant 历史格式，不能直接把 tool 结果伪装成用户消息。本项目的分析结果输入格式和对应监督需在实施前另行设计、训练及验证；本轮 FLEURS 测试不注入任何 thinking 结果。

训练数据后续复用[倾听轨迹](research_design/listening.md#7-倾听训练数据与训练目标)和[表达轨迹](research_design/speaking.md#4-表达训练数据与训练目标)，依据当时实际可见的输入独立审核控制动作，不从 Layer 2 建议字段复制。保留普通接话、主动澄清、合理等待、用户附和和打断，以及 CoT 未返回或过期的对照。CoT 输入块在 XTurnix 训练中屏蔽预测损失，只监督合法动作；与 Layer 1 表达监督、Layer 2 可选的 CoT 生成监督分别记账，保持两种能力的训练和测试隔离。

## 5. Layer 0 系统附和的后续安排

Layer 0 继续只预测“发出系统附和／继续等待”，不接管 XTurnix 通用控制、澄清价值或措辞生成。未来输入可结合声学特征、ASR、控制动作及必要历史；正文由 Layer 1 表达路径提供，经同一仲裁器发声。系统附和不代表用户让轮，播放中不叠加另一条音轨。

后续先规划 200 个独立试标机会，再根据覆盖与资源规划 2,000—5,000 个审核后的训练事件；这些只是附和专项参考，不是 thinking 流语料总量。按原对话和说话人分组，重叠窗口不算独立样本，FDB 评测资料不参与训练或阈值选择。

可从语音编码器加小型分类头开始比较声学与文本特征，最多 3 个配置串行、各最多 3 epoch、worker≤2，保留最佳与最终两个检查点。具体模型、阈值、特征和正文方案在实施前确定，本轮不启动。验收重点为机会级命中、误触发、重复、迟到及真实播放，不能靠沉默或只统计附和频率证明合理。

## 6. 后续完整话轮评测

此前取消的 FDB 测试继续暂停。未来如另行开展完整系统评测，应固定 Nemotron 与表达/TTS 配置，对比旧控制和 XTurnix；控制诊断可用相同参考播放，自由生成结果另报实际播放覆盖。

| 数据 | 历史数量 | 后续用途 |
| --- | ---: | --- |
| v1.0 candor_pause_handling | 216 | 用户停顿时误接话 |
| v1.0 synthetic_pause_handling | 137 | 不完整表达与受控停顿 |
| v1.0 candor_turn_taking | 119 | Smooth TOR、漏接话、提前接话与延迟 |
| v1.0 synthetic_user_interruption | 200 | 用户打断后的控制与响应 |
| v1.0 icc_backchannel | 55 | Layer 0 实现后的系统附和诊断 |
| v1.5 user_backchannel | 99 | 用户附和时误停 |
| v1.5 user_interruption | 200 | 有效打断与用户附和的区别 |

数量须对正式输入清单重新核查；成对和重复回放不增加独立场景数。原有官方评分提交为 `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`，采用时重新冻结，v1.5 单独锁版本。

正式输出与输入等长，尾窗仅诊断。Pause TOR 与 Smooth/Interruption TOR 的优劣方向分开，延迟与漏答/失败覆盖同时报告。控制 token 到达不是可听响应延迟，内容质量也不能由 TOR 推出。现有 FLEURS 两组件测试不承担上述验收。

## 7. 拟交付文件与说明

拟交付内容按[XTurnix 工作单](issue/XTurnix/README.md)分别实施，本次只创建工作单，不创建代码空壳。实施时按同路径提供中文说明，X-Talk 同步维护其对应文档。

| 拟实现 | 对应说明 | 作用 |
| --- | --- | --- |
| `scripts/remote/setup_xturnix_env.sh`、`configs/xturnix_fleurs_test.json` | `docs/scripts/remote/setup_xturnix_env.md`、`docs/configs/xturnix_fleurs_test.md` | 隔离环境准备与模型/协议/资源配置冻结 |
| `scripts/remote/xturnix_fleurs_test.py` | `docs/scripts/remote/xturnix_fleurs_test.md` | 固定输入、真实时钟回放、ASR/控制事件及独立评分 |
| `scripts/remote/run_xturnix_fleurs_job.sh` | `docs/scripts/remote/run_xturnix_fleurs_job.md` | 远端预检、串行预热、限额与退出清理 |
| `tests/test_xturnix_fleurs_test.py` | `docs/tests/test_xturnix_fleurs_test.md` | 少量可手算事件，验证时窗、版本、提前 start 与失败分母 |
| X-Talk 控制适配与相关事件（后续） | X-Talk 对应中文文档 | XTurnix 决策进入唯一仲裁路径，播放状态回传 |
| Layer 0 与控制器训练入口（后续） | 实施文件的同路径说明 | 各自职责下的数据构造、训练与验证 |

复用现有[原生 Nemotron 服务](scripts/remote/nemotron_asr_service.md)和持续音频传输，不恢复已撤回的专用部署、回放与评分脚本。

## 8. 环境、资源与实施顺序

本地使用 `interclarify-dev`。远端只读复用现役 Nemotron 环境与模型，XTurnix 使用独立 conda，锁定官方实现和模型 revision，不升级或覆盖现役 ASR/TTS/评分环境。资产位置按[远端约定](remote_workspace.md)预检。

| 阶段 | 上限 | 时间与并发 |
| --- | --- | --- |
| 数据与环境准备 | 4 CPU、8 GiB RAM、下载并发≤2 | 1 小时，单作业 |
| 两组件推理 | 优先 1×24 GiB GPU、8 CPU、32 GiB RAM、batch=1 | 4 小时，仅 1 个作业、1 条活动音频 |
| 汇总评分 | 4 CPU、8 GiB RAM、worker≤2 | 停止推理服务后执行 |

首轮预检峰值，不自动增加卡数或工作数。新增资产≤10 GiB、报告/trace≤2 GiB、启动可用盘≥30 GiB；模型只读复用，不复制大权重。触限则停止并保留失败，日志与检查点有上限。

实施顺序为“冻结 FLEURS 输入与历史 ASR 基线 → 锁定 Nemotron/XTurnix/停顿策略 → 实现回放与独立评分 → dev 预热及少量冒烟 → 100 条正式回放 → 独立评分和报告”。权重 revision、停顿检测与阈值、接口轮询周期和请求缓冲上限须在正式回放前固定。真实模型测试在远端执行；XTX-001—003 已完成，XTX-004—006 尚未实施，本次不运行正式回放或评分作业。
