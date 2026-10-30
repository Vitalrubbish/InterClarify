# SoulX 前端采集与写入

对应 `scripts/runtime/soulx_frontend.py`。`SoulXFrontend` 绑定一个已加载的 SoulX 模型、一个 SharedContext 与稳定的会话／话轮 ID；不启动下游 LLM 或播放器。构造时检查五状态 tokenizer 往返、配置 ID、FunASR 标签字典和后处理文件摘要。

2026-10-30将转写来源提为类属性，默认仍为SenseVoice。Nemotron子类可复用音频账本／状态采集，跳过与其无关的SenseVoice后处理校验；开轮和关轮使用相同固定来源，不让子类快照被误写成SenseVoice。SenseVoice默认行为不变。

`instrument_methods()` 校验官方 `service/model.py` 摘要，只对四个方法做内存 AST 变换。五处音频拼接、一处窗口裁剪、一处 argmax 采集与一处最终状态采集必须全部匹配，否则拒绝启动；不编辑共享上游源码。官方 ASR 门控、文本归一化和 KV 修订保持。

`feed_audio()` 接收有限的16kHz单声道float32包，禁止并发操作模型，处理缓冲内所有完整块。数组弱引用账本追踪真实采样范围、历史回补和合成填充；`slice_spans()` 同步窗口裁剪。控制器 reset 保留未处理输入 PCM，模型 KV 与识别窗口仍重置，话轮不关闭。

每个处理块校验真实采样起点连续，防止reset导致漏块、重复或倒序。调用方在真实输入EOF后将 `delivery_phase` 切为 `drain`；排空期间来源和状态均保留诊断，正文不再更新，状态不产生有效控制行为。

`observe_asr()` 保存 generate 原始结果及标签，再事务发布正文版本，不等待状态或整轮识别。`observe_control()` 保存同来源的控制文本与实际 delta token；`observe_state()` 在服务合并／reset 前发布修正后的五状态、原预测、过滤原因和已提交版本依据。远场与完全合成音频状态仅作诊断。只有有效 nonidle 可经注入的活动输出查询和停止回调取消匹配输出，每个 output ID 幂等；未提供这两个回调时只发布 Context。

识别实参在保留采样账本后显式转为float32，防止官方float64初始化缓存把输入提升为双精度；事件记录实际ASR输入类型。这不改变窗口或来源，但属于数值精度调整，需与未调整的历史运行区分。

`close_turn()` 保留最后在线文本。关闭后的来源结果标排空，不改主快照；`detach()` 恢复原方法，供同进程下一样本复用模型。提交重试复用原事务，不重复 GPU 前向；失败超限由调用方终止运行。单模型串行、PCM总量4MiB、单包≤800ms，其他边界由 Context 检查。

识别回调统一使用 `asr_call_id`，并用真实回调契约测试检查后处理之前的发布。异常中止使用 `detach(aborted=True)` 恢复模型方法，不再追加可能跨过失败事务序号的关闭事件；原始错误和最后在线记录保留。每个turn使用独立producer ID，同会话下一话轮可从自身序号1开始。

可选 `audit` 回调在发布前保存源头审核，`on_commit` 在提交后供实际消费者读取。回调不应调用模型或播放。真实接入应由音频运行时管理接收队列；本文件不自建网络服务。
