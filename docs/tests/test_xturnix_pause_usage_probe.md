# test_xturnix_pause_usage_probe.py

只核验诊断回放中的三个关键合同：当前末尾 pause 保持 pending、续说后才成为句内 token；gate 与一次性 latch 防止提前或重复 start；旧前缀回退在该单调参考回放中显式失败。真实 ASR 修订处理属于后续实现，不以本测试冒充完成。

另只读运行固定官方源码对应的现有 pause/gate 单元测试，检查参考框架真实方法与回放合同一致。模型效果仍由远端 PT 作业验证；这些测试不生成控制质量成绩。
