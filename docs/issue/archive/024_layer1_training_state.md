# Issue 024：实现有限训练及完整训练状态恢复

状态：完成，已归档。父任务：[005](005_training_runtime_and_resource_probe.md)。2026-10-20 用户授权启动005。实现提交`c21a352`，真实验证作业`job-179242817730774595080-xuan-zhang`；结果见[005报告](../../../reports/layer1_training/issue005-probe-20261020/README.md)。

## 范围

复用已通过017的完整官方加载器，只更新既有q/v LoRA。实现assistant目标mask、按有效token归一化的梯度累积、AdamW、线性scheduler、梯度检查点、固定随机种子及原子checkpoint。保存权重、optimizer、scheduler、Python/NumPy/CPU/CUDA RNG、确定性序列顺序和采样游标；仅在完整optimizer步边界恢复。

32/100均指004 r5训练集中的原始对话，不是序列数。试跑采用T3既定视图分配，不重新分配或增加曝光。资源长度测试从已审计事件计划重新编码完整micro-turn窗口，不截断控制目标；重新编码同时核验原4096序列，短跑窗口不覆盖正式数据。三个正式训练臂仍保持同一初始化及共同窗口规则。

新增`train_layer1.py`、`configs/layer1_training.yaml`及同路径说明；测试覆盖mask、恢复身份/游标、断点后真实更新一致性、越权参数变化和输入损坏。真实模型测试交给025远端单卡作业。005完成之前不放行006。

## 完成条件

- [x] 实现及中文镜像文档齐全，本地4项轻量契约通过，远端7项全部通过。
- [x] 远端真实模型完成更新，112个既有LoRA张量改变、冻结参数完整摘要不变。
- [x] 未中断与干净进程恢复的loss、LoRA及optimizer/scheduler/RNG/游标完全一致，未放宽容忍度。
