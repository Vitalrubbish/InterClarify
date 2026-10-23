# test_xturnix_listen_calibration.py

对应 XTX-010 的五个关键契约测试，不加载模型：观察点之后结束的词不能进入输入；同会话多个话轮不能跨集合；重复 keep 不稀释话轮级误抢话且失败末端保留；阈值只用开发记录选择并按预算校准；空当前文本保持 Listen、分数 null，不伪造模型正确样本。

通过已有 conda 运行 `python -m unittest discover -s tests -p test_xturnix_listen_calibration.py -v`。真实模型结果由远端独立作业验证，不用这些合成小例证明实际质量。
