# FDB真实ASR与TextTurn动作监控

对应 `scripts/remote/textturn_fdb_replay.py`，由TT-005／006和TT-007共用。只监控TextTurn，不生成回答、助手正文或TTS，不模拟生成和播放，不改变现役控制路径。

`ActionState`是动作监控的状态记录器，每条从Listen开始，`apply`只允许start切Speak、stop回Listen、keep维持，拒绝非法动作。状态没有计时自动复位。`snapshot`保留完整在线ASR前缀和实际控制窗的no-voice连续数；助手正文固定为空、生成完成标志为null、历史保持冻结空列表，不因start分割或伪造新对话。记录状态转移事实不代表真实开口或播放。

`load_audio`逐文件核对冻结摘要，按清单在Turn Taking拼接一次5秒静音，Pause不拼接。`replay`独立建立ASR会话，以80ms包按真实时钟发送，使用SharedContext及时发布转写；重复文本不形成新更新，控制步骤核对Context文本和版本，下游只读消费者核验一致性。

控制聚合器从清单读取160ms或480ms周期，分别每1或3个真实解码完成步骤形成完整周期。LatestControlWorker至多一个在途、一个待处理快照，合并范围保留。记录HTTP完整返回、输入状态、动作应用后状态、ASR前缀、耗时及controller_transition；不加载用于模拟助手的tokenizer，不调用旧ShadowState。

记录原录音结束、实际输入结束和EOF。EOF排空单列，不足完整周期的尾窗只记录、不提交，不追加no-voice或凑齐观察。输入结束后的在途调用保留实际返回，不截断时刻。

`main`只接受action_only协议，在独立新目录串行处理正式100条或两条清单外冒烟，逐例刷新trace与进度。case_start包含周期和状态模式；失败保留，清理失败则停止后续录音，避免泄漏会话。旧模拟回答的trace不得混入新结果。

移除模拟回答源于用户2026-10-25明确纠正；原r1—r3保留为撤回记录。480ms与160ms用相同输入和状态规则重新执行，真实模型只在远端调度节点现有conda中运行。
