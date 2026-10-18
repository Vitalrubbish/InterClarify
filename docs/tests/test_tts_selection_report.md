# TTS 证据收集门禁测试

`tests/test_tts_selection_report.py` 使用临时证据目录验证：非零包装退出默认拒绝，显式接受测量后包装错误时保留原始 127，缺失样本或音频请求失败仍被拒绝。测试类 `CollectionGateTests` 只构造文件元数据，不生成或假冒真实模型结果。
