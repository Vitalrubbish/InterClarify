# 原1k ASR延后句读训练

2026-10-21，状态：已提交远端调度，训练及候选重载待完成。用户明确要求先在按新策略重建的原1k上训练，不扩至3k。

条件`ASR_R4_delayed_punctuation`，源数据见[077结果](../issue077-asr-punctuation-data-r2/README.md)。原1000条train的新ASR视图、2048窗口上限、2480序列、1201531监督token，batch1/累积2、单epoch1240步、warmup124、每207步保存。AdamW 2e-5、加权CE控制权重1/10/5/2/1与040一致；最终epoch为唯一候选，不从旧训练权重续训。数据视图与旧T2不同，不能只把结果归因为某一标点字符的影响。

源码冻结`179ac88`，独立worktree为远端训练根目录`source/issue078-179ac88`；现役训练conda，单4090/8CPU/32GiB、worker0、并发1、8小时总上限，训练5GiB/总目录6GiB、空闲盘至少20GiB。正式入口执行数据/加权目标/旧新协议回归，再训练并在干净进程重载验证，不自动运行FDB或上线。

远端输出：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue078-asr-punctuation-r1`，提交收据与作业日志位于训练根目录`submit_logs/issue078-asr-punctuation-r1-receipt.txt`及`issue078-asr-punctuation-r1.log`。提交前`vc list`无其他作业、磁盘空闲约591GiB；数据重建r2已退出0。

本地8项因果句读、30项原管线、17项训练相关契约与张量检查通过，另有5项加权loss及4项候选检查通过；部分集合存在覆盖重复，不把总数当独立样本。正式配置已通过真实冻结证据校验；shell语法、链接和Git空白检查通过。数据机器通过和60条代理阅读不冒称人工签署，人工状态仍pending；用户本次直接训练授权单独登记于078协议。

训练执行、所有对话/序列曝光、冻结参数一致、loss有限及重载ID复现仍待实际完成；不预先填写成功或FDB能力提升。
