# TT-010 动作平衡重训

2026-10-26 11:29:51监控核查：测试尚未提交，原训练作业仍为唯一Running作业。baseline开发集评估已完成，pilot第1轮1894/1894窗训练已跑完，当前pilot-dev-epoch-1为2501/88947；尚无训练退出码或最终candidate。等待器PID1400303存活，11:29:28状态为waiting_for_training、jobs为空，无TT-011测试run目录。最近资源样本11:29:44显存2756MiB、资产2882289283字节、报告689819778字节，空盘934375408KiB，均在限制内；实际pilot三类有效权重质量各约631.3333，平衡配置已进入训练阶段。当前仅有部分开发预测，不据此判断质量或放行。此次仅只读检查远端，未修改／重启作业。

2026-10-26用户明确授权重新启动训练并取消训练任务时间上限。本次使用1%正例覆盖门槛及keep／start／stop各1/3有效损失，从固定Qwen3-0.6B基模重新训练；不把旧pilot目录当成恢复检查点。完整数据继续复用tt-010-fulltraj-r1，train9977窗／21来源、pilot1894窗／4来源、dev88947窗／200来源，全部逐拍监督。

训练配置max_wall_seconds=null，训练进程13800秒timeout与外层14400秒timeout均已移除；训练按pilot／full各两轮及质量gate自然终止。资源检查、退出清理和异常退出码保留。单GPU24GiB／8CPU／32GiB，显存22GiB、资产10GiB／报告2GiB、空盘30GiB停止线不变，10秒资源采样。未主动向vc提交时长限制，平台自身调度策略以实际信息为准。

本地现有conda interclarify-dev下64项TextTurn回归及bash语法检查通过，包含取消训练时限后仍检查显存／磁盘、等待器无截止且启动阶段无日志的检查。完整数据审核绑定新训练配置和当前损失实现，提交前须远端核对并使用独立审核文件；不覆盖原远端audit或训练产物。

已提交并确认Running：`job-179298196307743501088-xuan-zhang`，pdgpu-4090，2026-10-26 10:32:43提交、10:32:46开始，实际设备RTX4090。run为`tt-010-balanced-20261026-r2`，远端独立源码为`~/parathink-textturn/source/tt010-balanced-r2`，冻结提交`b57b2ce931c8e2bd31e571f93b287823aa53061f`；已核实GitHub push和远端fetch回执。调度OriginalCmd直接运行bash入口，不含timeout；run_manifest中max_wall_seconds为null，1%门槛与三类等份损失均确认加载。

截至本次部署取证，开发集基线评估已2501/88947，未宣称pilot发生优化器更新或候选质量通过。资源最近采样显存1976MiB，TextTurn模型／数据／run约2.67GiB，run报告约0.63GiB，空盘约891GiB，均低于原停止线。资源采样文件为`submit_logs/tt-010-balanced-20261026-r2.resources.txt`，训练日志同前缀`.training.log`，退出码待任务结束后写入`.exit_code.txt`。

远端现有conda数据环境的5项gate及8项续接契约均通过，单CPU／线程1／2GiB／60秒；另核对12个冻结数据文件摘要、新训练配置、当前损失helper及新run不存在等条件，预检退出码0。独立审核文件`submit_logs/tt-010-balanced-20261026-r2.audit.json` SHA256为`a842775ffa7c18bbad6f5274ffbb140f2bc5cf95c978cbe76688a4f552c6be3a`，训练配置SHA256为`f3a44db1ea5c6b390478f25bd9d7fe1794efdaf00fad6ba5e2755bc3317be5b5`；旧远端数据audit未覆盖。新审核内容见[audit.json](audit.json)。

TT-011按既有授权重新绑定本轮真实run、job及源码提交，在新目录准备冻结协议及等待器；等待训练无应用层截止、等待器无总时长timeout。训练成功、最终full候选放行及学习重载核查通过且无活动作业后，先160ms UltraChat150例，再160ms action_only FDB100条；测试每项7200秒及全部单作业资源上限保留。旧stopped状态和失败证据完整保留。


## 训后续接实际部署

新协议为`~/parathink-textturn/submit_logs/tt-011-external-20261026-r2.protocol.json`，绑定上述训练run／实际job／冻结源码；training_wait_deadline=null，SHA256为`36e33306c8408e9139fb8b4a4fe8a3758a980e85b3e00b53143cd5af2d38fcd5`。准备目录为`dataset/tt-011-external-r2`，prepare退出码0，重新核对历史150例UltraChat和100条FDB的资产与前缀审核；prepared SHA256为`ecb33e58780b29e0d3999e14c51e3ceab042ea5cab659812df2d6de071e76bbc`。

等待器Python PID1400303，独立session，nohup／setsid启动，无外层timeout；已核实存活及至少2次状态更新，单CPU亲和0、地址空间2GiB。当前waiting_for_training、jobs为空，新测试尚未提交。状态`dataset/tt-011-external-r2/state.json`，事件同目录events.jsonl，后台日志`submit_logs/tt011-r2-waiter.log`。后续预定run为`tt-011-ultrachat-20261026-r2`和`tt-011-fdb-20261026-r2`，候选或训练不满足条件则停止，不回退旧权重。

部署证据见[deployment.json](deployment.json)，含实际run_manifest、调度命令、回执、资源样本、进程限制与绑定协议，取回SHA256核对为`0e02acce13b41642ccfe8e8959c8f512a535d0100df124daac616b2a6b66ec82`。旧r1训练和失败等待器证据保持原样。本次交付为重新启动及监控部署，训练完成与测试质量均待后续实际结果。
