# `tests/test_duplex_a4_replay.py`

`A4ReplayTests` 在无 GPU、无模型环境下检查远端验收驱动的证据判定。覆盖缺少实际 interruption token、不同 response 的停止事件、teardown 停止不得冒充打断、reset 后音频仍在增长时判 FAIL、协议错误、WAV 时序、源码清单确定性，以及本轮新增的播放证据与场景音频解析：已播文本前缀单调、`response.finish` 不得超出已确认前缀、播放窗口内 ASR 更新计数、`pause` 场景基础门禁、`--scenario-audio` 覆盖解析。`PlaybackTests` 继续验证中断时保留已播前缀、丢弃未播尾部。避免把模拟成功或旧响应事件当成 A4 通过。

```bash
conda run -n paratalker-dev env PYTHONPATH=src:. python -m unittest tests.test_duplex_a4_replay -v
```

该离线测试验证驱动正确性；真实 ASR、MOSS、官方权重和 FDB 由 [远端任务单](../xtalk_a4_remote_acceptance.md) 执行。
