# TextTurn 受限训练与开发集比较

对应 `scripts/training/train_textturn.py`，属于 TT-002。真实模型仅在远端 conda 和单 GPU 调度作业中运行。

`load_controller` 加载固定 Qwen3-0.6B，按 TT-001 注册四个新 token，使用语义词的均值初始化新增行；既有词表的预留行不能当作已训练动作。LoRA rank 16、alpha 32，更新注意力和 MLP 投影；通过 PEFT trainable_token_indices 训练四个新增输入行，保持基模 tied embedding 与输出头一致。其余基模冻结。保存时不复制整份 embedding，重载后比较动作分数及新增行。

`train_stage` 使用 AdamW、1e-4、5% warmup、BF16、单样本、累积16、最多2 epoch。每个输入只在最后位置预测动作，历史及正文没有损失。先比较初始化模型与至多2000窗 pilot；开发集机会得分改善且误抢话／误停均未明显回归才进入至多10000窗完整训练。每轮按开发集选唯一最佳候选，不读取独立测试。仅保留最佳及最终 adapter；最后写候选冻结清单。

`evaluate` 逐窗比较当前状态的两个合法动作，记录完整预测及耗时，调用独立评分函数按机会汇总。这里是给定观察和状态的离线文本决策比较，不是自由运行的在线回放；传输、排队及实际播放延迟须由 TT-003/004 单独验收。重载检查与必要的小批次训练机制核验随该入口完成。

训练首批反传检查新增 token 梯度非零且有限；另保留 keep/start/stop 各一个训练探针的前后 loss。重载必须恢复完全相同的新增行和动作分数，不能只检查 adapter 文件存在。

作业检查完整数据摘要、环境版本、显存22GiB停止线、资产10GiB及报告2GiB预算，并遵守单作业4h；TT-010已由用户取消旧累计8 GPU小时限制。开发集不改善则保存停止原因，不自行扩大规模或搜索参数。

## TT-010完整轨迹适配

新版本从manifest.split_files加载gzip逐拍数据，按complete_trajectories检查0起连续窗口，pilot/full/dev均不删拍。load_controller按manifest中的既有ID注册四或五个控制输入token，新增finish输入行用finish语义词均值初始化，加入PEFT可训练输入行并随adapter保存／重载；预测候选始终只有状态合法的keep/start/stop。

配置loss_policy必须与冻结数据一致。train_stage只打乱轨迹顺序，保留轨迹内部时间顺序；使用textturn_loss.weighted_action_loss及阶段固定平均权重，所有样本都反传，finish等输入位置没有预测目标。仍是逐快照独立前向，不将整段拼成超长文本或跨快照反传。旧数据无loss_policy时保持原无权重训练行为。

本轮用户取消原累计GPU剩余预算限制，授权核查通过后直接启动；新专用提交入口保留单作业资源上限和pilot质量放行。数据允许训练不代表质量通过，仍以实际作业及开发集结果记录。

## 2026-10-26 低门槛放行及动作损失平衡

新训练配置保留与manifest完全相符的基础loss_policy，另用loss_balance在每个阶段调用stage_loss_weights，固定三类有效损失份额各1/3、平均权重1。以snapshot_id绑定有效权重，轨迹打乱不会错配；数据文件中原始loss_weight不变。摘要同时保存基础／有效质量、缩放系数及范围。没有loss_balance时仍采用原阶段平均基础权重。

每轮在history与best_selection记录development_gate明细，正常接话／陈述／打断各至少1%且完整分母，保留综合分改善和误动作回归约束。选模优先合格候选，合格full优于合格pilot，同阶段再按综合分；不合格轮次保留供诊断。pilot_gate只决定是否继续full，最终选择另存online_gate.json并重新检查，选中full且全部条件通过才continue_online；不能把pilot的放行布尔值直接用于最终权重。无新门槛配置的历史运行仍按原综合分选模。

真实模型训练与保存重载验证仍在远端调度节点执行。本次只修改上述损失和放行，不改开发集、损失计算的完整词表CE、标签、采样顺序、时限及检查点保存时机，不启动远端作业。

2026-10-26用户进一步授权重训并取消时间上限：check_budget在max_wall_seconds为null时跳过时长检查，仍核对显存及空盘；数值配置继续用于历史或明确限时的任务。新训练入口内外均无timeout，训练按既定epoch和质量gate终止，异常和资源停止线仍有效。
