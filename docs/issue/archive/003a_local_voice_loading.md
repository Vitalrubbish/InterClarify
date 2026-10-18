# Issue 003a：修复 Kokoro 0.9.4 本地音色加载

状态：完成，2026-10-18。父任务：003。首轮作业 `job-179232775620066075571-xuan-zhang` 在预热失败，退出1。KPipeline.load_voice 以CPU torch.FloatTensor 判断直接pack，CUDA Tensor落入字符串分支而调用split报错。

使用官方支持的本地 `.pt` 路径交给load_voice加载、缓存，再由pipeline移动到模型设备；不联网下载、不修改音色。修复后用新源码快照重跑短/长预热、增量与取消测试，保留首轮失败。真实结果通过后归档。


完成证据：冻结源码v6、r4-asr / r4-tts均退出0，真实模型自动验收通过，报告见 `reports/english_integration/20261018-r4/`。原始失败和旧分段结果保留远端，修复不改写旧结论。人耳听感仍由003c单列。
