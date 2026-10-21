# Issue 035：官方训练设置重核

2026-10-20根据用户要求重新调研，范围排除上下文窗口长度。完整中文对照见[训练模式对照（历史版本）](https://github.com/Vitalrubbish/InterClarify/blob/717fcf037d471d07be41172b5b69b0dd404cfcb6/docs/layer1_training_comparison.md)。本项没有修改训练、模型或测试配置，没有申请GPU作业。

## 证据

- [public_sources.json](public_sources.json)：重新请求官方GitHub main树、model.py和README，记录URL/摘要/文件列表。当前树列11个文件，未公开训练循环与完整数据生成器；model.py与本项目冻结版本相同。
- [evidence.json](evidence.json)：官方发布train_cfg、文件摘要，以及三臂实际训练manifest的优化器参数、数据统计、初始化身份和更新张量数。远端只读再次核对固定官方source revision、train_cfg和model.py摘要，与既有资产清单一致。
- 本轮实际源码为c388a2f，每臂1,000条对话、1,214步、2,428序列、1,193,875监督token，非10k。对照不把原始对话数、训练序列数和步数混为同一量。

## 需要修正的表述

论文§4.1明确声明控制类别加权，但官方公开的推理包装器forward使用普通CrossEntropyLoss，且未公开训练器；只能说“我们与论文描述的加权目标不同”，不能称已经从公开训练代码确认作者实际训练loss，也不能据公开推理包装器反证作者没有加权。

论文明确warmup500步，但未详细给出其后scheduler曲线；本轮37步warmup后线性衰减是本项目配置，不能宣称与作者退火完全相同。论文报告batch32，但设备batch和累积分解未知，不能擅自按8卡再乘32或反推出epoch。

论文“动态构建”不等于已公开“每步/每epoch重新抽样”。本轮epoch0事件计划预先冻结可确认，作者的重采样时机、packing及loss分母未知。LoRA r16/alpha32/dropout0.05/bias none和gradient checkpointing则有发布元数据支持，不能误列为差异。

## 与当前失败的关系

已确认重要差异包括初始化、embedding/head冻结、论文类别加权未采用、学习率/batch/warmup/步数，以及数据抽样和事件边界。它们都可能影响行为，但现有结果没有唯一识别哪个造成持续talking。下一次试验需保留单变量归因，不同时改变loss、可训练范围及初始化后将收益只归于一项。

部署使用Nemotron/Kokoro而官方用DSM/Kyutai是另一层分布变化，不能混入训练优化器比较；双方原训练范式都是合成文本，不能说官方训练使用真实在线ASR标签。两份规范文档在本地仍为用户原有删除状态，本次只新增独立研究报告。
