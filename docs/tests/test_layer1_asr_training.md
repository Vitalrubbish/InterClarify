# ASR单epoch训练门禁回归

`tests/test_layer1_asr_training.py`使用`AsrTrainingTests`在临时目录冻结模拟证据，检查原1k/ASR臂/单epoch与加权目标不可漂移，摘要改变、来源切分改变、旧复核记录或伪造人审通过均拒绝。有效条件允许本次用户已授权的机器审计加代理阅读流程，人工pending不写成passed。

测试不加载模型；真实训练及候选重载仍由远端078执行。
