# SharedContext 当前值检查

对应 `tests/test_shared_context.py`。三个CPU场景使用真实SharedContext验证：更正与删除直接覆盖、读者副本隔离及无历史存储；错误帧／倒退音频／关闭与容量边界不破坏当前值；并发读取不会混合不同帧的正文和状态。

使用既有conda运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p 'test_shared_context.py' -v`。不加载模型，不将存储正确性当作识别质量。
