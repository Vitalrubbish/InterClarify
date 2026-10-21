# Issue 078：在重建的原1k上训练ASR延后句读条件

状态：已完成并归档，2026-10-21，训练及候选重载退出0。077机器审计和60条代理复核已完成，用户已明确授权先在该1k上训练。人工签署保持pending，不伪造人审通过或继承040豁免。

独立条件`ASR_R4_delayed_punctuation`，只用原1000条train的新ASR视图，dev/test不训练。完整官方初始化、既有112个q/v LoRA、冻结base/embedding/head；不从旧1k候选续训。单epoch、2048、batch1/累积2，加权CE及1/10/5/2/1控制权重、AdamW 2e-5等优化器参数沿用040；步数按新索引ceil(sequences/2)，warmup为10%向上取整，每约1/6 epoch保存，固定最终候选。

新增独立数据/训练配置及协议，引用077manifest、机器审计、训练索引和完整官方资产摘要。共享训练器增加ASR臂和新协议校验，旧040协议继续按原约束验证；候选加载器登记新条件但保持完整权重/冻结参数/生成ID重载验证。

远端调度单4090/8CPU/32GiB、worker0、并发1，整体8小时硬限，训练5GiB/总输出6GiB、空闲盘至少20GiB；不在登录节点训练，不自动增卡/改精度或失败重训。启动前核对作业及预算，使用现役conda和冻结worktree，保留失败及退出码。训练后干净进程重载，不自动切换线上模型或提交FDB。

- [x] 新配置与数据、索引及授权契约冻结，相关回归通过。
- [x] 调度正式训练并完成单epoch，所有1000对话及全部序列恰好曝光，尾批不重复。
- [x] loss有限、112个LoRA变化且冻结参数不变，候选干净进程重载/生成ID复现通过。
- [x] 报告、最终权重摘要、资源和退出码回收，完成后归档；训练执行通过不代表FDB能力提升。

已冻结ASR train2480个2048窗口、1201531监督token，单epoch1240步、warmup124、每207步保存；配置与协议见`configs/layer1_asr_training.yaml`和`configs/layer1_asr_protocol.yaml`。共享入口移除当前重载脚本已不支持的`verify`子命令，改用现有直接参数入口。原040 T2协议仍按原授权验证，本次不续训旧权重或自动评测。

源码`179ac88`已推送，远端采用独立worktree；执行路径和预算见[本轮报告](../../../reports/layer1_training/issue078-asr-punctuation-r1/README.md)。最终1240步/2480唯一序列/1000对话/1201531监督token全部核验通过，112个LoRA变化且冻结参数不变，候选重载生成ID复现通过，退出0。训练约41.68分钟、显存allocated峰值19.11GiB、RSS峰值15.63GiB。

最终checkpoint SHA256为`d1f4d05e4ed1b29dbe8550ffaa02be389673975f7929b33ec1420ef2d70c44a1`；080补充[loss分析](../../../reports/layer1_training/issue078-asr-punctuation-r1/loss_analysis.md)。本单没有自动运行FDB或切换线上候选，旧T2_R3继续保留对照身份。
