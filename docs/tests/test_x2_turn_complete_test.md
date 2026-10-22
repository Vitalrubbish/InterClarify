# X2-Turn 固定输入、实时回放与指标测试

`tests/test_x2_turn_complete_test.py` 用少量可手算记录和本地模拟 WebSocket 验证 X2Q-009、011、012、013 的合同，不加载权重，不生成模型实测结果。

## 类与核心方法

- `FleursDataTests` 保留冻结数据阶段的四项检查：文件名哈希排序、最小 manifest 复核、音频篡改和 test/dev 混用。`fixture` 与 `write_wav` 创建临时输入，结束自动回收。
- `MetricTests` 使用 `trace` / `event` 构造客户端接收记录。检查 complete 闭区间两端、重复帧、提前或仅 EOF 后出现、空输出、异常 ID、控制器事件不计分和中途失败。ASR 检查手算 S/D/I、空转写删除、失败 null、独立于 complete、负末端延迟、标点变化和 EOF 补字；汇总用不同参考长度区分语料 WER 与逐例平均，并保留缺失 trace 的失败分母。另实际加载固定版本 normalizer。
- `StreamingTests` 使用独立发送与接收的模拟服务。其中完整回放按真实时钟发送 160 ms 原始 PCM 和完整 5 秒静音，核对块间隔、累计采样数、末块 40 ms、输入中收到原生状态、窗后 EOF 及 EOF 后文本。故障检查覆盖断连、服务错误、无效 JSON 和排空超时；只有故障测试缩短时间常量。运行级检查确认失败仍有记录、manifest 字节摘要一致、dev 不算正式样本及 run_id 不可覆盖。

## 本地运行

在既有 conda 环境补装固定 normalizer 后执行：

```bash
conda run -n interclarify-dev python -m pip install whisper-normalizer==0.1.12
conda run -n interclarify-dev python -m unittest discover -s tests -p test_x2_turn_complete_test.py -v
```

共 15 项测试，模拟完整尾窗约需 5 秒。测试仅证明协议与统计逻辑；真实模型表现、有效 delay 和远端资源证据由 X2Q-010、014 验证。
