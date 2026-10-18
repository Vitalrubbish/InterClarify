# Kokoro 分段合成服务

`KokoroEngine` 从本地 snapshot 加载 config、权重及 af_heart pack，独占合成锁；音色用本地.pt字符串路径交给KPipeline.load_voice缓存，避免0.9.4将CUDA Tensor误当字符串。synthesize 完成短文本段，24kHz 浮点音频经 resample_poly 转 48kHz mono PCM16。`SegmentRequest` 限制 160 字符并携带 generation/sequence。`create_app` 只提供 health 与 `/v1/synthesize`，回传身份、格式、PCM 和计算耗时。main 先预热短句与较长句，再开放服务。

服务无播放器、不推测未来文本。客户端断连不能强制中止底层 GPU 调用，旧结果由客户端代际检查丢弃，释放耗时需远端报告。启动参数 `--snapshot` 必须指向冻结资产，模型在远端独立 conda、独占 GPU 上执行。


资源与来源补充：health记录加载耗时和进程峰值RSS，作业收尾保留service /proc状态，GPU逐秒采样；ASR关闭记录等待worker释放耗时。采集manifest标为integration_diagnostic_only且禁止训练，保留源音频摘要与失败。TTS核验增加真实Kokoro经RuntimeAdapter、TTSManager、协调器和播放管理器执行短附和、有效插话停旧音频及新响应，headless确认不等同扬声器实播。
