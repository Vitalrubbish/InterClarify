# Nemotron累计文本到SoulX的适配

对应`scripts/runtime/nemotron_soulx_frontend.py`，继承已有音频账本、原生五状态采集及输入reset保留行为。使用唯一Nemotron来源，不调用SenseVoice。

`accept_asr_event()`独立接收有序前缀／真实解码完成事件，校验generation、序号、前缀及保守观察上界，立即事务发布来源与正文；词内增量原样追加，EOF后只留诊断。发布短锁不包围GPU计算，因此ASR文字不等待SoulX完成。

`_asr()`保留官方音频门控前向，选取观察上界不超出当前音频的源版本；门控未开时暂不消费。整段派生文本经既有归一化和SoulX tokenizer编码。`token_patch()`计算新旧token公共前缀，纯追加时只注入新增token；末词重分词时定位受影响音频块，重建本generation的多模态KV。重放最多256块／4096文本token，不发布伪状态、不撤销过去判断。

每块额外检查所有已保存文本token串接后必须等于本次选定的完整派生前缀，避免KV修订漏字或重复消费。

`observe_state()`在短锁内同时保留Context当前版本及实际消费版本；`_reset_controller()`保留ASR和话轮，只重建控制缓存，并从已消费尾词重新预置派生文本基线，避免将`inter`／`net`当成新消息。`_recognize()`只读取已有前缀，用于原生完成分支，不再整轮识别或抢读未来文字。

该路径是独立组合探针，源前缀不可变不保证识别正确。回调的`consumed_samples`含预取，故作保守上界使用，不宣称精确词时间或步骤对齐。完整词提交及Layer1输入编码仍需另行实现。
