# 原1k ASR延后句读训练

2026-10-21，状态：训练及干净进程候选重载已完成，远端退出0。用户明确要求先在按新策略重建的原1k上训练，不扩至3k。

条件`ASR_R4_delayed_punctuation`，源数据见[077结果](../issue077-asr-punctuation-data-r2/README.md)。原1000条train的新ASR视图、2048窗口上限、2480序列、1201531监督token，batch1/累积2、单epoch1240步、warmup124、每207步保存。AdamW 2e-5、加权CE控制权重1/10/5/2/1与040一致；最终epoch为唯一候选，不从旧训练权重续训。数据视图与旧T2不同，不能只把结果归因为某一标点字符的影响。

源码冻结`179ac88`，独立worktree为远端训练根目录`source/issue078-179ac88`；现役训练conda，单4090/8CPU/32GiB、worker0、并发1、8小时总上限，训练5GiB/总目录6GiB、空闲盘至少20GiB。正式入口执行数据/加权目标/旧新协议回归，再训练并在干净进程重载验证，不自动运行FDB或上线。

远端输出：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue078-asr-punctuation-r1`，提交收据与作业日志位于训练根目录`submit_logs/issue078-asr-punctuation-r1-receipt.txt`及`issue078-asr-punctuation-r1.log`。提交前`vc list`无其他作业、磁盘空闲约591GiB；数据重建r2已退出0。

作业`job-179258410706612068732-xuan-zhang`，北京时间20:01:47提交，实际节点`d6-hpc-gpu-069`、NVIDIA GeForce RTX4090，BF16可用。启动回归已通过，正式训练1240步与候选重载均完成，最终退出0。

本地8项因果句读、30项原管线、17项训练相关契约与张量检查通过，另有5项加权loss及4项候选检查通过；部分集合存在覆盖重复，不把总数当独立样本。正式配置已通过真实冻结证据校验；shell语法、链接和Git空白检查通过。数据机器通过和60条代理阅读不冒称人工签署，人工状态仍pending；用户本次直接训练授权单独登记于078协议。

## 最终验收

逐行复核1240条日志：2480个序列ID全部唯一、1000个原train对话全部曝光、有效监督token累计1201531，各步游标连续；所有loss/梯度有限，加权分母与五类目标统计一致，目标重算最大残差小于1e-5。112个LoRA张量变化、冻结参数不变，完整官方初始化及最终权重在干净推理进程恢复一致，固定prompt生成ID复现通过。该探针证明加载一致性，不代表自由生成接话能力通过。

最终checkpoint SHA256：`d1f4d05e4ed1b29dbe8550ffaa02be389673975f7929b33ec1420ef2d70c44a1`，重载报告与实际文件一致。训练耗时2500.9秒（41.68分钟），优化循环2309.3秒（38.49分钟）；显存allocated峰值19.11GiB、reserved峰值22.97GiB，RSS峰值15.63GiB，总目录约350.2MiB，均在预算内。

证据：[训练summary](training_summary.json)、[候选重载](candidate_reload.json)、[回收摘要](collection.json)。完整step日志与权重留远端，未重训、未切换当前线上模型、未运行新FDB。人工数据签署状态仍pending，执行/重载通过与能力提升分别记录。详细loss分析见[loss_analysis.md](loss_analysis.md)。
