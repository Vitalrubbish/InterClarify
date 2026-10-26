# TT-011 外部回归运行记录

最新结果：训练于02:14:21超时退出124，续接器停止；UltraChat及FDB均未提交。pilot两轮全部keep，full第1轮评估不完整，无正式候选。详细指标见文末“结果核查”；下方部署记录为历史。

2026-10-26按用户指令启动，原TT-010训练仅只读监控。截至00:25:56最近核查为pilot第2轮开发集评估14001/88947，训练仍Running，未发布退出码或最终candidate。不得把中间best当作已放行候选，尚未提交测试。

## 修复与审核

新入口绑定训练run／配置／manifest、五token注册（finish=151673）、adapter和基模摘要、开发集gate、学习验证与保存重载验证。UltraChat使用独立生成与模拟播放时钟，增加output_id、played_text、用户版本、runtime_events及latest_terminal；模拟播放完成后仅一次finish，stop后迟到完成无效。FDB保持action_only，没有助手正文、生成、播放或finish。

保留TT-008的30来源：30个干净文本会话和120个已录制ASR场景。逐前缀审核冻结60个可判定停止请求、48个完整附和；7条残字M未知、5条无附和转写不造机会。新主评分为因果可判定前缀后1000ms内影子有效stop，另列自然结束、非Speak与观察缺失；旧停止词评分仅保留辅助。正例仍主要是旧停止请求模板，不能推论一般非附和更新的完整覆盖。接话及停顿语义覆盖不足明确保留未知，行为计数单列。

FDB复用TT-007同100条录音及原摘要，真实Nemotron、160ms，保留旧两臂行为口径，补充新转写窗口stop及严格大于960ms持续Speak。新旧候选对照只做相同资产回归，ASR重新运行可能存在时间差异，不冒称盲测或真实TTS闭环。

本地现有conda `interclarify-dev` 下54项TextTurn回归通过（含7项新增必要契约），bash语法检查通过；尚未执行真实模型接口冒烟，该步骤在训练放行后的远端调度节点执行，不占正式分母。

## 续接与资源

续接器保存状态、提交意图、job ID回执及调度历史，通过互斥锁及落盘意图防重复提交；未知提交回执停止人工核对，不自动补提。训练退出码0且调度Completed／EndTime存在，候选核查通过且没有活动作业后，冻结候选与清单，先UltraChat，释放GPU并重查后FDB。运行失败停止，执行成功而质量差仍继续交付。

每项1×24GiB GPU／8CPU／32GiB，最多一个活动作业，单项7200秒并预留60秒清理；显存22GiB、资产10GiB、报告2GiB、可用盘30GiB停止线。旧累计GPU额度已取消，不据其阻止测试。复用现有conda和权重。训练13800秒／外层4小时上限保持，不修改原训练源码。

远端冻结源码为`37d95439c10bada5496e62bc9149396b1594435d`，已收到GitHub push及远端fetch回执，worktree为`~/parathink-textturn/source/tt011-external-r1`。新协议及准备产物在`dataset/tt-011-external-r1`，prepared SHA256为`d541cdd683273ead23f7cb49fb4132232afb4576979d7e9f38ad2652a0f5c4f6`；prepare退出码0，历史资产核对通过。远端现有conda数据环境`~/miniconda3/envs/interclarify-x2-turn-data`的7项必要契约全部通过，单CPU、线程1、2GiB／60秒限制有效。

等待器于00:24:53进入`waiting_for_training`，00:25:25及00:25:56两次更新均确认原训练Running、jobs为空；实际Python PID为136137，独立session supervisor PID为136136（PPID=1），不依赖当前SSH存活。RSS约35MiB，CPU亲和为单核0，地址空间上限2GiB，外层12小时超时。启动使用nohup＋setsid，已按实际Python进程更正PID文件，不能把最初setsid父进程136135当成存活证据。完整检查见[deployment.json](deployment.json)。

续接状态：`~/parathink-textturn/dataset/tt-011-external-r1/state.json`；逐次状态：同目录`events.jsonl`；后台日志：`~/parathink-textturn/submit_logs/tt011-waiter.log`。准备日志和远端契约日志分别为`tt011-prepare.log`、`tt011-contracts.log`。成功放行后run预定为`tt-011-ultrachat-20261026-r1`与`tt-011-fdb-20261026-r1`；截至上述核查尚未产生测试提交回执，真实模型接口冒烟和最终结果均待训练结束，本工作单保持打开。

## 2026-10-26 09:38 结果核查

训练未成功完成，外部测试未启动。调度记录为Terminated，2026-10-25 22:24:10开始、2026-10-26 02:14:21结束，占卡13811秒（3小时50分11秒），训练退出码124。结束时间与入口内层13800秒timeout一致；不是原累计GPU余额耗尽，未修改单作业时限。当前无活动作业。

已完成baseline、pilot两轮训练及各自完整88947窗开发评估；pilot_gate的continue_full为true，随后full第1轮9977窗训练进入评估。full-dev-epoch-1仅留下60001/88947窗预测（67.46%），没有summary；第2轮full未运行。最后周期日志每500窗输出并刷盘，最终实际保存记录数也为60001，不能把最后日志当完整评估。部分full预测为keep57640／start2106／stop255，无推理错误记录，但这只是开发集有序前缀，不能当全量指标或外部成绩。

| 已完成开发指标 | baseline | pilot第1轮 | pilot第2轮 |
| --- | --- | --- | --- |
| 正常接话成功 | 0/800 | 0/800 | 0/800 |
| 其中陈述接话成功（上项子集） | 0/400 | 0/400 | 0/400 |
| 打断成功 | 102/400（25.5%） | 0/400 | 0/400 |
| 停顿误start | 296/737（40.16%） | 0/737 | 0/737 |
| 附和误stop | 120/242（49.59%） | 0/242 | 0/242 |
| opportunity_score | 0.2715008 | 0.4 | 0.4 |
| 88947窗动作计数 | keep66127／start10736／stop12084 | keep88947 | keep88947 |

pilot平均训练损失从第1轮2.397094降到第2轮1.217740，但两轮开发预测均为全部keep，不能据损失下降判断动作能力已学会。当前综合分将三项正例成功与两项负例正确平均，全部keep取得(0+0+0+1+1)/5=0.4，高于较差的初始基线；gate只要求综合分改善且两项误动作率不显著回归，因而放行。这个门槛存在退化候选识别缺口，本次仅记录核查结论，未修改评分、门槛、模型或重新提交训练。

best_selection仍为pilot第1轮（同分不替换），best adapter SHA256为`5382dd6bda2e928ccdf08a28cf4f8363dec97927bfc4ffe8b750379d09d04fec`；final是pilot第2轮，摘要`aca4064a0e418213a5e91b00fc3ddd2e5fb3efaa46f741563504fbaf21b70c57`。保存逻辑位于完整轮次评估之后，因此未完成评估的full第1轮权重没有保存为新检查点，不能把best或final目录称为已训练完成的full模型。candidate.json、learning_verification.json、reload_verification.json及full-history.json均缺失，最终候选与保存重载检查未交付。

续接器于02:14:38记录`stopped`，原因`Training failed: exit_code=124`，jobs为空；无TT-011测试run目录，无新UltraChat/FDB调度记录。两项测试均为未提交、未运行，不存在新测试成绩，不能记为测试失败或零分。等待器已退出，符合训练失败即停止的合同。TT-010和TT-011均保持未完成；本次没有重启训练、修改单作业时限、补提测试或改用pilot权重。

远端核查只在现有conda数据环境进行标准库CPU读取，单核／2GiB／60秒；没有模型加载或GPU任务。完整证据见[training_inspection.json](training_inspection.json)，包括调度历史、退出码、完整pilot指标、逐阶段预测计数、缺失产物及摘要；取回后SHA256核对为`80a6a982447a0b57ba50ea76430994d0ed4b3a4cf09441c7135564133f7dbf5f`。远端原文件为`~/parathink-textturn/inspection/tt011-20261026-status/inspection.json`。
