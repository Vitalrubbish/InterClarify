# `tests/test_xtalk_round1.py`

## 整体作用

离线检查远端准备工具的版本锁定、GPU 分配隔离和并发 TTS 收音行为。测试不下载权重、不启动 GPU，也不替代远端模型服务验收。

## 测试设计与核心方法

`RoundOneTest` 使用临时目录、模拟下载 API 和模拟流式 TTS。检查已有模型锁定在再次下载时保持相同 revision、配置变更拒绝复用旧锁；GPU 逻辑编号只映射到作業可见设备；音频接收与文本发送并行，报告正确记录 flush 前收到音频和 WAV 采样率；`--stream-chunk-words` 会把单段文本按词切成分片推送，报告记录 `text_chunk_count` 与切分结果。模拟失败不会被解释为真实模型结果。
