# 英文新组合运行配置

显式选择 NemotronStreamingClient 与 KokoroSegmented，80ms 传输与160ms ASR模型分块分开；600ms Layer 1 时钟不变。Kokoro 分段为12/160字符及600ms完整词聚合期限（无词边界的残词等后续输入或finish），句界/finish可提前提交，并裁去各段冗余首尾静音，独占现有播放链路。关闭声学VAD对持续流的截断，不启用Layer 2/3。该配置无类和方法，不自动启动服务，不表示质量和FDB通过。旧X2配置仍为诊断。
