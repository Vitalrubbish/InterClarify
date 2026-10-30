# TT-010 完整轨迹加权训练

2026-10-26最终状态核查：作业于02:14:21因13800秒内层时限结束，调度Terminated、退出码124，占卡13811秒。pilot两轮dev88947窗全部keep，虽通过现有综合分gate（0.4>基线0.2715008），接话／打断均0；full第1轮训练后开发评估只保存60001/88947窗，未完成选模及学习／重载验证，无candidate。best／final仍为pilot第1／2轮，full权重未保存；TT-011续接器正确停止，两项外部测试未提交。详见[核查结果](../20261026-tt-011-external-evaluation/README.md#2026-10-26-0938-结果核查)及其原始证据。TT-010保持打开；以下启动记录为历史。

用户已明确要求所有选中轨迹逐拍入训、用损失权重控制重复keep，并授权核查后直接启动远端训练；随后明确取消旧累计GPU剩余预算限制。单作业资源和时长上限、来源隔离及质量放行不变。本次沿用TT-010，不新增issue。

## 数据与损失实际交付

旧按类别选两拍的r2版本保留作基线，不作为本次训练输入。新数据位于本地`artifacts/textturn/tt-010-fulltraj-r1`，远端目标`~/parathink-textturn/dataset/tt-010-fulltraj-r1`。选中轨迹没有删拍，完整事件与r2逐字节相同。

| 集合 | 来源 | 完整轨迹 | 窗口 | keep | start | stop |
| --- | --- | --- | --- | --- | --- | --- |
| train | 21 | 84 | 9977 | 9851 | 84 | 42 |
| pilot，train完整来源子集 | 4 | 16 | 1894 | 1870 | 16 | 8 |
| dev | 200 | 800 | 88947 | 87747 | 800 | 400 |

10000训练窗上限保持，通过完整来源组选择而非轨迹内抽样控制规模。已审阅91459优先，其余按固定种子哈希排序；下一完整来源组超预算即停止，不截断、不挑短轨迹凑数。21来源分别保留疑问／陈述×正常／打断四种对照，陈述start50%；不能称其覆盖原160个训练来源。用户检查的91459:question:normal全部70拍都有正损失权重。dev保留原200来源全部窗口，不抽样评分。

每条轨迹、每个状态／类别的keep组有K拍，单拍权重min(1,2/K)，该组总权重最多2；start／stop每拍各2。每拍都预测合法动作并反传，只有输入及正文、finish等位置仍为-100。训练阶段使用固定平均原始权重归一化，避免单样本下加权mean抵消权重。train的原始权重总质量约1346，其中keep1094、start168、stop84；固定平均权重0.13491029367544974。该配置是本次控制重复暴露的起点，不宣称已证明质量最优。

每轮打乱轨迹顺序，轨迹内逐拍按时间输入，不随机重排帧、不删除暂停或播放尾窗。仍是当前因果快照上的独立动作预测，不跨快照反向传播。tokenizer注册第五个输入token `<finish>`（151673）；训练入口初始化并学习该输入行，动作候选保持keep/start/stop。新格式接话评分包含start之前的listen／正常空观察窗口，不能以正确锚点掩盖提前start；旧冻结格式保持原评分。

本地CPU共47项TextTurn回归通过，其中5组检查加权损失、梯度、累积归一化、完整来源选取和注册。独立核查全部100818个train/pilot/dev文件窗口（pilot为重复子集）通过：无缺帧、全正权重、合法动作／掩码、keep组质量、tokenizer实际编码、pilot完整子集、70拍审阅样例和原始事件一致性。构造61.438秒，gzip产物约109MiB，CPU单线程／2GiB／600秒／512MiB上限内完成；无本地GPU模型测试。

## 远端执行状态

远端预检无活动作业，现有conda及固定Qwen3-0.6B可用，可用盘约892GiB。模型约1.5GiB、数据485MiB、旧run约503MiB，原资产停止线有余量。数据传输包SHA256为`99ec86d23b445ddce2f3bb9a1ca625817f12da1b889349eb4ec8785741fd43de`；上传后须远端核对摘要，不能以本地成功代替远端准备完成。

已提交并确认Running：job-179293824747465991917-xuan-zhang，pdgpu-4090，服务器时间2026-10-25 22:24:08提交、22:24:10开始。源码冻结为`56102849e3e88209a9943fd1ffa605395534526e`，远端worktree为`~/parathink-textturn/source/tt010-fulltraj-r1`，run为`~/parathink-textturn/runs/tt-010-fulltraj-20261025-r1`。实际设备为RTX4090；远端conda中5项损失边界测试通过，数据包摘要与本地完全一致。训练入口已完成模型／数据加载并持续输出baseline-dev进度，最后核查7001/88947；当前是开发集基线阶段，尚不宣称发生优化器更新、pilot／full完成或质量通过。单作业1张24GiB GPU／8CPU／32GiB RAM，一个活动作业，显存22GiB、训练13800秒／外层4小时、资产10GiB／报告2GiB停止线；仅取消旧累计剩余额度，不自动取消任何质量门槛。pilot开发集改善且误抢话／误停未明显回归才进入full，保留失败，不以启动作业当作质量通过。

## 复现及摘要

[冻结入口](../../../docs/archive/scripts/training/freeze_textturn_full_trajectories.md)、[损失函数](../../../docs/archive/scripts/training/textturn_loss.md)、[完整性核查](../../../docs/archive/scripts/analysis/audit_textturn_full_trajectories.md)、[远端提交](../../../docs/archive/scripts/remote/submit_textturn_full_training.md)。旧在线ASR、噪声及真实播放覆盖不足的结论不因本次训练启动而改变。

manifest SHA256：`21357f70fb2d382c1ed79741d094aaee9378ec609c5215c7db1afc096b477989`。

| 文件 | SHA256 |
| --- | --- |
| train.jsonl.gz | `c25ccccdbfe02e75d42746cf77728bcd03396aa839bafa8e5be5d84e153924b1` |
| pilot.jsonl.gz | `d4a3ced7895863ec178db03306c7f0f0d5318b18f7f6d8e8b03d526a6d5adc90` |
| dev.jsonl.gz | `a1bfa7bb34e5d84b01b4acd74e46e2494198a768156b43f3452e88bcdb2e64c3` |

完整逐文件摘要及权重分母见manifest，audit.json绑定该manifest和训练配置，训练前仍校验冻结文件。大体积产物不进Git。

实际日志：`~/parathink-textturn/submit_logs/tt-010-fulltraj-20261025-r1.training.log`；调度回执和源码摘要同目录保存。运行环境为torch2.11.0+cu128／transformers4.57.1／peft0.19.1／tokenizers0.22.2。作业结果、质量放行和重载验证待完成后补充，TT-010保持打开。
