# TT-011 外部回归运行记录

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
