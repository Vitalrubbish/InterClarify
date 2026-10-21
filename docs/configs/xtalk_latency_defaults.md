# X-Talk当前延迟默认值补丁

`xtalk_latency_defaults.patch`只记录062本轮默认值变更：Kokoro首段300ms、后续独立1200ms，运行适配器默认KV复用，以及相应默认值测试。使用`git apply --unidiff-zero`应用；基线为049/061已验证的X-Talk运行快照，不用于缺少此前增量TTS/缓存实现的原始上游。

X-Talk独立仓库按其AGENTS约定保留未提交变更；InterClarify保存这份小型补丁及远端源码摘要，避免重复提交整个旧运行快照。该补丁不包含权重或原始测试数据，没有独立类和方法。
