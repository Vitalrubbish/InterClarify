# Nemotron 在线 ASR 服务

`AudioBuffer` 以 condition 等待真实到达的 PCM16，保留 FFT 重叠并限制积压 30 秒；EOF 追加明确记账的 2 秒解码静音，暂停不结束。`NativeNemotron` 使用锁定 EN processor 的 160ms lookahead=1、FP32、单次 generate 特征迭代器，保持 RNNT 缓存。`NemotronSession` 在后台接收 IDs，检查文本单调并记录原始/可见增量和时间；`snapshot` 不需要新音频。`NemotronService` 单活动流，create/get/close 以 UUID 隔离，关闭等待 worker 退出，超时隔离服务。warmup 要求两次真实语音输出与清理。

`load_pcm16` 先以float32读取PCM/IEEE float容器，核验有限值及16kHz单声道，再缩放为PCM16，避免soundfile直接int16读取float WAV时舍入成零。取消worker超时会清除ready，禁止健康检查继续声称可用。

HTTP `/v1/session` 分配、`/v1/recognize` 输入、`/v1/session/{id}/result` 独立读取、DELETE 取消；is_final 仅记录暂停，end_stream 是实际 EOF，不传入 LLM。health 仅在真实预热后可用。默认 16kHz mono PCM16 传输，80ms 包由客户端选择，不等同模型分块。每包摘要、接收时刻、前缀版本、消费量和关闭原因写日志。启动必须在远端 conda 调度作业内使用 `--model` 和 `--warmup-audio`；服务没有离线回退。预热源通过soundfile读取，以兼容IEEE float WAV，转PCM16后送模型，分别记录源文件与PCM摘要，不改写原文件。


资源与来源补充：health记录加载耗时和进程峰值RSS，作业收尾保留service /proc状态，GPU逐秒采样；ASR关闭记录等待worker释放耗时。采集manifest标为integration_diagnostic_only且禁止训练，保留源音频摘要与失败。TTS核验增加真实Kokoro经RuntimeAdapter、TTSManager、协调器和播放管理器执行短附和、有效插话停旧音频及新响应，headless确认不等同扬声器实播。
