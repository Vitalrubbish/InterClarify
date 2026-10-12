# `tests/test_duplex_a4_replay.py`

`A4ReplayTests` 在无 GPU、无模型环境下检查远端验收驱动的证据判定。覆盖缺少实际 interruption token、不同 response 的停止事件、协议错误、WAV 时序及源码清单确定性；避免把模拟成功或旧响应事件当成 A4 通过。

```bash
conda run -n paratalker-dev env PYTHONPATH=src:. python -m unittest tests.test_duplex_a4_replay -v
```

该离线测试验证驱动正确性；真实 ASR、MOSS、官方权重和 FDB 由 [远端任务单](../xtalk_a4_remote_acceptance.md) 执行。
