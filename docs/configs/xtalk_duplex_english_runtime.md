# 英文新组合运行配置

显式选择 NemotronStreamingClient 与 KokoroSegmented，80ms 传输与160ms ASR模型分块分开；600ms Layer 1 时钟不变。Kokoro 分段为12/160字符及600ms完整词聚合期限（无词边界的残词等后续输入或finish），句界/finish可提前提交，并裁去各段冗余首尾静音，独占现有播放链路。关闭声学VAD对持续流的截断，不启用Layer 2/3。该配置无类和方法，不自动启动服务，不表示质量和FDB通过。旧X2配置仍为诊断。

2026-10-21 延迟候选：首段 max_wait_ms=300，独立 continuation_wait_ms=1200；micro-turn 仍为 0.6 秒。duplex_kv_cache_enabled 显式启用跨请求缓存；远端对照生成基线配置覆盖这两个开关，不改权重或正文过滤。
