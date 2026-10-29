# SoulX 前端采集与写入

对应 `scripts/runtime/soulx_frontend.py`。`SoulXFrontend` 绑定一个已加载的 SoulX 模型、一个 SharedContext 与稳定的会话／话轮 ID；不启动下游 LLM 或播放器。构造时检查五状态 tokenizer 往返、配置 ID、FunASR 标签字典和后处理文件摘要。

`instrument_methods()` 校验官方 `service/model.py` 摘要，只对四个方法做内存 AST 变换。五处音频拼接、一处窗口裁剪、一处 argmax 采集与一处最终状态采集必须全部匹配，否则拒绝启动；不编辑共享上游源码。官方 ASR 门控、文本归一化和 KV 修订保持。

`feed_audio()` 接收有限的16kHz单声道float32包，禁止并发操作模型，处理缓冲内所有完整块。数组弱引用账本追踪真实采样范围、历史回补和合成填充；`slice_spans()` 同步窗口裁剪。控制器 reset 保留未处理输入 PCM，模型 KV 与识别窗口仍重置，话轮不关闭。

`observe_asr()` 保存 generate 原始结果及标签，再事务发布正文版本，不等待状态或整轮识别。`observe_control()` 保存同来源的控制文本与实际 delta token；`observe_state()` 在服务合并／reset 前发布修正后的五状态、原预测、过滤原因和已提交版本依据。远场与完全合成音频状态仅作诊断。只有有效 nonidle 可经注入的活动输出查询和停止回调取消匹配输出，每个 output ID 幂等；未提供这两个回调时只发布 Context。

`close_turn()` 保留最后在线文本。关闭后的来源结果标排空，不改主快照；`detach()` 恢复原方法，供同进程下一样本复用模型。提交重试复用原事务，不重复 GPU 前向；失败超限由调用方终止运行。单模型串行、PCM总量4MiB、单包≤800ms，其他边界由 Context 检查。

可选 `audit` 回调在发布前保存源头审核，`on_commit` 在提交后供实际消费者读取。回调不应调用模型或播放。真实接入应由音频运行时管理接收队列；本文件不自建网络服务。
