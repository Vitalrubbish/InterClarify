# Issue 040：延后启动全量加权训练

2026-10-20 用户明确要求直接启动全量训练，使用最新数据和加权 loss。本轮独立条件 `T2_R3_delayed_start`，一次性第三轮例外见 [040b](../../../docs/issue/040b_delayed_start_full_training.md) 和006。原两轮协议及结果保留，不从第二轮最终权重续训。

输入为 `issue040-delayed-start-data`，清单 SHA256 `86c0faca1e1a12d3c7cf1fa0144e53a6a83166a8454ad48d986b24d40a97761d`。全部1000条train、T2去句读视图、2048、2469序列/1201531监督token；1epoch共1235步，最后一批只有1个序列，仍按实际目标权重和归一化。完整官方初始化、112个既有q/v LoRA、冻结embedding/head；AdamW 2e-5、warmup124后线性衰减。控制类别权重为talking/finish/interruption/backchannel/thinking=1/10/5/2/1，正文及EOS权重1。

[训练器索引](full_train_index.json)在远端由`ProbeDataset`重新编码全部训练序列而得，生成退出0，SHA256 `9032074e05eeb1de7c1c93c396f1e61f0b1e59df67ee21b2c618d167eca9bbfc`。正式入口同时验证配置、索引、最新数据审计、实际运行数据及官方资产摘要，不允许旧r5回落。用户直接训练授权仅允许省略新增模型短跑及在机器审计通过、人审pending时开训，不修改原数据或伪造人审/实测通过。

资源1×4090/8CPU/32GiB，worker0、并发1，整体8小时硬上限；训练输出5GiB、总输出6GiB、可用盘保留5GiB。保存点206/412/618/824/1030/1235，固定最终epoch；保留全部中间检查点用于恢复排错。超预算、身份不符、OOM或非有限loss失败，不自动改参数或重训。正式训练结束后脚本自动在干净进程重载完整候选并复现生成IDs；本次不自动提交FDB。

本地`ml-hw1` conda 的加权loss/候选10项和新条件4项测试通过；`paratalker-dev`缺PyTorch的初次相关测试未通过，因此转到有PyTorch的现有conda完成核验。数据管线32项在上一阶段本地/远端均通过，新作业启动时再执行全部32项及14项训练契约/梯度检查。没有运行模型短跑。

提交和实际训练启动证据待调度器返回后更新。
