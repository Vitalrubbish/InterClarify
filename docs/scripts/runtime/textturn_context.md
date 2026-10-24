# TextTurn 共享转写与控制窗

对应 `scripts/runtime/textturn_context.py`，属于 TT-003。实现不加载模型或播放器。

`SharedContext` 是单一转写来源，按session/turn保存最新版本并保留有界有序更新。`publish_user_transcript`检查重复版本、乱序、前缀追加和生命周期；重复不入库，旧版本不覆盖，新版本改写明确失败。空轮可以打开，关闭产生单独版本；EOF不会冒充语义完成。`get_user_turn`读取快照，`read_user_transcript_updates`按游标读取，保留范围外显式要求重新同步。

`TranscriptConsumer` 只读消费同一Context的版本，验证不重复注入及最终正文一致，记录实际消费游标。`ControlWindowAssembler`只接受连续的真实160ms完成步骤，聚合三个步骤；当前窗口累计转写新增文字，整窗无字才使用no-voice。EOF尾窗单独flush，不足三步不伪造480ms覆盖。窗口保留首次输入可见、末步完成、聚合等待及范围，供延迟计算。

消费者审核记录最多保留4096个版本，当前正文按最多128个turn有界保存；过期读取明确报缺口。待处理窗口合并后的排队起点保留最早就绪时刻，不能用最新窗口就绪时刻掩盖排队等待。

`LatestControlWorker`至多一个在途调用及一个待处理快照，新的待处理观察合并累计范围和转写，记录合并数；不会取消在途请求，也不追加固定等待。异常显式返回失败，关闭可等待排空并保留尾窗。该模块只组织影子控制输入，不拥有TTS或播放执行权。
