# SoulX 前端契约测试

对应 `tests/test_soulx_frontend.py`。五个小场景使用真实解析、整理和发布方法，替换模型依赖，不运行 GPU。覆盖原始标签／数字／缩写、唯一滑窗及歧义、状态前文字可读、空值与关闭排空、五状态／远场、停止幂等及不连续音频账本。

运行：`python -m unittest discover -s tests -p 'test_soulx_frontend.py' -v`。全部五状态的协议覆盖不等于音频模型覆盖；真实预测另由远端回放报告。
