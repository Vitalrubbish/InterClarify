# TextTurn v2 trace评分回归

对应 `tests/test_textturn_trace_scoring.py`。七项必要回归覆盖：ASR不完整不能冒充误停或正确保持；已观测误stop不能被后来keep抵消；缺少停顿控制记未知；整段参考或未来续说不改变未审核start的判定；审核hash、Context版本、1秒截止和陈旧输入检查；停止词需明确指令；未知保留在计划分母且阻止虚假通过。

全部使用极小合成事件，不加载模型。全量1200例历史trace在远端conda下单线程重评；单元测试不替代实际重评。
