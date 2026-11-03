# test_shared_context.py

对应 `tests/test_shared_context.py`。本测试验证当前唯一前端路线的 Context 边界：

- 开轮固定为 `x2_streaming_asr`／`joint`，初始正文为空、`step_id=-1`、`committed_groups=0`。
- 读者取得的是副本，修改副本不会改变 Context 当前值；Context 不保存历史事件或版本字段。
- 关闭后拒绝再次开轮，`release_closed_turn` 后才允许新话轮。
- 话轮数容量与空标识符边界。
- 多线程读取不会混合不同帧。
- 五类状态 token ID 与冻结值一致。

联合提交的事务、真实采样范围、EOS 闭合组和状态字段校验由 `tests/test_independent_frontend.py` 覆盖。
