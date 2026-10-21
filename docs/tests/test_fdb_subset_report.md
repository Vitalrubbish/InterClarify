# FDB子集评分边界检查

`tests/test_fdb_subset_report.py`的`SubsetReportTests`检查子集评分仅改变独立调用中的两轴预期数量为5，并恢复完整语料的119/200约束；不会把10例子集宣称为完整评分。用25例小型WAV和报告核对原窗播放/尾窗才播放分别统计、缺样例失败、官方输出混入尾窗失败，不加载真实模型。

conda下运行`python -m unittest discover -s tests -p test_fdb_subset_report.py`，真实回放和官方对齐仍在远端调度完成。

浮点WAV回归：/PCM16输出的真实WAV容器回归，使用已有soundfile依赖；时长相同应通过，不能因编码格式不同而拒绝有效输入。远端该测试移入含音频依赖的客户端conda执行。
