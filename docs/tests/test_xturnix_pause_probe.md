# XTurnix 停顿探针测试

`tests/test_xturnix_pause_probe.py` 只验证探针的文本构造，不加载模型、不访问 GPU、不读取远端数据。

- `no_pause` 返回原文。
- `pause_at_end` 只在末尾追加一个 `<|pause|>`。
- `pause_mid_and_end` 保留原文并产生两个 pause token，一个在指定偏移、一个在末尾。
- 随机中段偏移落在 20%—80% 的空格边界，便于逐条复算。

真实动作比较由 `scripts/remote/run_xturnix_pause_probe.sh` 在调度 GPU 上执行；本地测试通过不代表 start 比例。
