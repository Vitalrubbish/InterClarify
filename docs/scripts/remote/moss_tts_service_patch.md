# MOSS 服务实验入口

`moss_tts_service_patch.py` 显式加载固定服务适配器，包装其 `_load_upstream_module` 后调用原 `main`；不修改上游 checkout。固定来源为 MOSS `58b20a0`、服务 `b3306b9`，由现有 launcher 核验完整提交。

`apply_service_patch` 包装 command queue 的 put/get、start/push/finish、音色编码缓存、生成和 codec；以服务 session ID 作为组件实验的 request/response ID，记录实际门槛与 prefix 信息。`ObservedQueue` 记录排队，`trace_scope` 在 worker 处理命令时恢复关联。原始队列时序和 codec 生命周期保持不变。没有真实声卡消费数据，不能声称已测扬声器延迟。

实验开关 `XTALK_TTS_GENERATION_BATCH_FRAMES` 默认 0，保持原列表路径；候选 2/4/6。开启时仅在该服务加载的 Session 子类中使用惰性帧迭代器：每次先生成至多上限帧，再由原 decoder 消费，随后原 worker 自动继续余量。start、push、end_text 都沿原方法调用；finish 的原单帧 drain 保持不变。没有额外 worker 或播放队列。close 时标记取消，在批次生成前、交付前及 PCM 入队前丢弃未提交数据。尚待远端验证，不能作为默认配置。

`main` 记录文件摘要和实际环境开关；所有优化关闭时仍可独立开启 trace。当前尚未观测到 socket 发送与真实播放，需在报告中明确缺项。

worker 包装器在退出时清理仍打开的 codec streaming context；正常 finish 已关闭时不重复关闭，close/异常退出也不会遗留共享 codec 状态。取消与 PCM 入队由同一提交锁串行化；等待供音后重新检查取消。已经进入客户端播放缓冲的数据仍须由原播放所有者丢弃，服务补丁不能撤回已交付音频。
