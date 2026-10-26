# UltraChat 正文注入重测

对应 `scripts/remote/textturn_ultrachat_retest.py`，服务TT-008。`freeze`在查看新模型输出前按固定哈希抽30个test来源，收录30个完整文本会话及120个既有语音场景；同一清单供两个周期使用。记录配置、来源、原始音频、ASR trace和文本文件SHA256。缺失或异常保留原场景，不换样。正文、音频和原始trace只保留在资产目录，不进入Git。

干净文本来自TT-001的用户增量时间线，忽略教师动作和助手可见正文；角色、轮次、附和关闭、尾窗与轮后等待来自原合同。ASR来自TT-004保存的在线transcript及decode_step，排除EOF排空；按原发布时间差真实时钟回放，时间原点为首个解码发布减其名义音频结束时间。它不是新执行的在线ASR，也不使用参考全文替换识别结果。480ms聚合3个解码完成，160ms每个解码完成；不足完整窗口不补观察。

`ReplayState`是唯一影子动作所有者。`begin`从空前缀启动回答，`advance`按名义周期发布8／3 token正文，保留字符完整性，记录计划与实际发布时间、累计token数和摘要，正常生成结束后经过固定毫秒尾窗转Listen。`update`维护独立用户轮及ASR版本，旧轮和已提交前缀进入history，当前用户字段只保留尚未提交部分。附和在其后首个既有生成观察前关闭。`snapshot`生成模型输入；`apply`验证动作合法性，start只提交该次请求看到的用户前缀，stop保留实际已发布的中断正文。生命周期已变更的迟到动作明确记为stale，不伪造生效。

`replay_case`以主线程处理事件、正文和动作；最多一个推理线程、一个待处理观察，合并只累积观察窗口，正文不依赖调用次数推进。完整请求、两个合法动作原始logit、真实返回及应用时间、用户更新和生命周期逐条写入trace。每场景单独落盘，运行异常不删除。`run`核对冻结资产与候选，按来源交错执行，实时更新progress及runtime；最后生成逐例CSV、详细JSON和汇总JSON。

`score_case`分开统计stop输出、实际生效、独立用户机会、960ms及时覆盖、已有明确停止词1000ms覆盖、自然提前结束及观察不足。用户继续说不自动作为语义打断金标；附和与无当前用户输入的误stop单列次数及Speak观察分母。连续Speak与同一用户轮首末实际更新区间求交，严格大于960ms计抢话，不补尾静音。保留未处于Speak的更新数、尾窗及正常结束覆盖；未观测到的自然结束不能当作stop通过。清晰文本与ASR分别汇总，不能混成真实ASR成绩；本实验没有空正文对照，不作正文因果结论。

TT-011增加`DuplexReplayState`，只在新配置`full_lifecycle`启用：沿用独立生成时钟，模拟播放落后一个周期，提供output_id、played_text、runtime_events、latest_terminal和用户版本。`terminal`在全部模拟播放完成后提交输入finish，stop闭合后迟到／重复完成仅记stale_callback；每次snapshot只消费一次终态。旧TT-008配置保持历史行为。正式回放出现运行失败将显式非零退出，阻止续接误判。新语义评分由`textturn_external_score`另存，原停止词诊断不代替它。

新生命周期快照同时去除历史user条目末尾句读，与TT-010可见user字段口径一致；保留原始冻结文本供追溯。


2026-10-27：DuplexReplayState.snapshot在去句读前记录text-update／empty-observation及实际准备／播放阶段，供新版训练／回放共用输入映射。旧候选保持其原编码。
