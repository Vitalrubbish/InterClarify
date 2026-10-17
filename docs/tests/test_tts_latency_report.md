# TTS 报告与筛选契约测试

`test_tts_latency_report.py` 验证：每个候选仅改变相对于指定 control 的一个变量；筛选总量确为 117 条；缺少结果文件不能判为作业完成；接收/消费 token 顺序、余量与图增量不会被空缺事件误判通过；配对比较不匹配不同文本或轮次；批次 PCM 一致性单独计数。CPU 夹具即可运行，不加载真实权重。

新增 combination suite 的配置契约：三臂各 27 条，共 81 条；仅 combined 同时启用 batch4/early/prefill4，前后 control 保持一致；默认单变量 suite 仍为 117 条。

组合报告的缺失目录回归要求无终态时 `complete=false`，组合失败不能被原control成功覆盖，报告不据此自动替换组件。
