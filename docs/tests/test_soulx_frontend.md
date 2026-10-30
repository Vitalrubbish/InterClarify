# SoulX 当前值前端检查

对应 `tests/test_soulx_frontend.py`。少量CPU场景核对：标签与原文映射；原生delta历史的替换、删除、空增量和英文连接；窗口原文只作诊断；每块联合写一次；整段结果覆盖草稿且reset先于联合发布；跨generation保留前文；空返回、错误、范围缺口及字符上限；float32识别与控制文字；五状态、远场拒绝、排空隔离、直接停止幂等及计算期间拒绝关闭。

测试执行真实前端采集与发布方法，以轻量状态模型替身触发顺序，不冒充GPU质量测试。`protocol_frontend()`构造无GPU前端，`run_frame()`提供带真实采样账本的160ms块和40ms前瞻。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p 'test_soulx_frontend.py' -v`。真实冻结模型的ASR门控、缓存及整段分支由远端回放验证。
