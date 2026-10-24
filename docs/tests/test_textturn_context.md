# TextTurn 共享转写测试

对应 `tests/test_textturn_context.py`，以三个契约测试覆盖版本幂等／乱序／回写拒绝与关闭、三步聚合及EOF短尾窗、一个在途加一个待处理时的累计文本合并。通过线程事件控制顺序，避免依赖固定睡眠猜测竞争状态。不加载模型或GPU，不代替远端Nemotron验证。
