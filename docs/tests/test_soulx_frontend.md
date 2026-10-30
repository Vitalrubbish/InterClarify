# SoulX 当前值前端检查

对应 `tests/test_soulx_frontend.py`。五个CPU场景核对标签与原文映射、窗口修订／缺口；ASR只暂存正文且每块联合写一次；complete后的整段识别及reset先于联合发布；float32识别和原生控制文字保持；五状态、远场拒绝、排空隔离、直接停止幂等及计算期间拒绝关闭。

测试执行真实前端采集与发布方法，以轻量状态模型替身触发顺序，不冒充GPU质量测试。`protocol_frontend()`构造无GPU前端，`run_frame()`提供带真实采样账本的160ms块和40ms前瞻。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p 'test_soulx_frontend.py' -v`。真实冻结模型的ASR门控、缓存及整段分支由远端回放验证。
