# 流式 TTS 独立评测入口

`scripts/remote/tts_selection_benchmark.py` 提供独立实验 HTTP 服务、客户端与结果汇总。它不接入产品播放队列。完整协议见 `docs/tts_selection_benchmark.md`。

`Backend` 封装 Pocket TTS、Kyutai DSM TTS 和 Kokoro（分段完整合成对照）的模型加载与原生音频块回调；`receive_moss` 直接调用 MOSS 既有 WebSocket 服务。`Handler` 在单请求服务中将原生块传为长度前缀 + PCM16，客户端按应用音频块记录收到时间。头部不算首音频包。模型常驻内存，所有计时包含请求和文本处理，排除加载。

`measure` 完成一次请求，先记录接收时刻，退出计时后写 WAV 与块轨迹，避免磁盘写入污染实时收包；`analyze` 将跨块波形合并后计算 10ms RMS，连续 30ms 达标才认定非静音，再映射回实际到达和播放时间线。`summarize` 分别汇总 cold、warmup 和 measured，请求错误保留，非静音缺失也计入缺失数。

命令分 `serve`、`run`、`summary`。`run` 使用固定 60 条 CSV，先 cold 1 条、预热 3 条，再正式 60 条，默认 180s 请求超时。超时或中途协议错误时停止该模型后续请求并返回非零，由节点包装器结束本模型服务进程组，避免生成线程泄漏后继续测量。失败请求已完成部分保留，未尝试样本不算成功。节点调用是独立集群作业。

试听保留所有正式 WAV；固定 6 条样本另行组织为匿名包。服务器上未实测前不宣称模型可运行。

Pocket 官方流式接口内部启用生成/解码线程，外层使用 `torch.no_grad()`；不能包在 `inference_mode()` 中创建跨线程 KV 缓存，否则 PyTorch 会拒绝线程内原地更新。其他模型保持原有 inference_mode。该兼容修复只影响 Pocket 启动验证，失败目录保留，正式 60 条在修复后新作业运行。
