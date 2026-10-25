# TT-011 候选身份核查

对应 `scripts/remote/textturn_candidate.py`。本模块只读取产物，不加载模型，不改变训练。`validate_candidate`绑定训练run、训练配置、数据manifest、基模及best adapter，确认full阶段成功、pilot开发集放行、学习改善和保存重载逐项通过。

五个token固定为keep/start/stop/no-voice/finish，ID为151669—151673；同时核对adapter配置中的可学习输入行和保存tokenizer，防止只替换权重路径却使用旧四token。`digest`分块计算SHA256，`read`读取JSON；核查结果作为候选身份快照，供续接器和GPU服务重复验证。旧候选由原入口管理，不自动替代未放行的新候选。
