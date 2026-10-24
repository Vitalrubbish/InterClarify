# TextTurn 固定候选文本评估

对应 `scripts/remote/textturn_evaluate.py`，属于 TT-004。仅在TT-002候选保存重载成功并通过开发集gate后运行独立测试。启动前核验candidate.json、adapter与TT-001 manifest摘要，保存不可变评估身份；不得按测试结果重选模型。

`evaluate_text`从固定测试完整计划读取19994个窗口，通过与训练相同的合法动作推理入口获取预测，保留失败及原分母。`score_file`输出逐机会CSV、汇总JSON和中文结论，明确这是给定状态的文本诊断，语音／Context／在线延迟门槛仍需TT-003真实链路；不能把离线模型耗时写成完整在线延迟。

单独远端调度、单卡，串行跟随训练。入口不安装依赖、不生成训练数据、不触碰现役播放器。
