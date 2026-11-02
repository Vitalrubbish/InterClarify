# 原生SoulX控制封装

对应实现：`scripts/runtime/native_soulx.py`，工作单NTF-015。`NativeSoulX`只发布控制状态和内部诊断，不向SharedContext写正文，不使用历史教师替换封装。

## 类与输入

`NativeSoulX`持有一个官方`TurnModel`、设备同步函数、状态回调及可选的活动输出／停止回调。构造时核对16kHz、2560主块、15360回看、640前瞻与英文SenseVoice配置；模型不能同时被其他封装持有。实际加载由[独立加载器](native_soulx_loader.md)负责。

`_Capture`核对官方`service/model.py`摘要及固定的5处拼接、1处窗口切片、原始状态和规则后状态采集点，只插入观察与PCM来源登记。原生音频编码、文字门控、SenseVoice识别与归一化、窗口修订、KV检查点、状态反馈、完整话轮识别均保留。子模块文件不修改。

## 核心方法

- `step(ledger, step_id)`从外部账本取得原生调用所需的2560采样，调用原有`process()`。调用内所有服务分支、reset及设备同步结束后才返回完成回执；不把状态回调当作整步完成。
- `_get_chunk()`调用原有切块函数，独立登记主块、回看和前瞻的真实／合成span及float32 PCM摘要。startup／reset首块含640合成采样，实际真实推进1920采样；后续无reset时推进2560。
- `_reset()`先保留审计信息，再调用原生reset，更新控制代次。外部供音游标退到已处理真实主块截止，未处理前瞻由外部账本继续供给；不恢复旧`model.buffer`。全局step_id、逻辑话轮与X2正文不重置。
- `capture_state()`在原生规则反馈结束后、服务分支清理之前采集原始token、规则后token、有效性、控制文字、实际处理／观察边界及可用时间。有效nonidle先调用停止钩子，再交付状态，每个output_id最多一次；要求同session且处于准备或播放阶段。回调必须短时、同步返回，不等待日志或消费者。
- `_observe_recognize()`记录实际输入摘要、dtype、采样span和原生返回文字；保持官方识别及异常处理行为，文字仅作控制诊断。回执分别给出`service_state`、`service_text`与`model_complete`／`wait_fallback`来源，不把外层speak改写为五状态complete。
- `pcm_bytes()`按拥有内存的底层数组去重，包含回看视图、ASR缓冲、历史主块与调用内仍存活的PCM。协调器通过`reserve_pcm`在拼接、切块副本和reset分配前检查总量。`cancel()`与短回调通过同一发布锁串行，返回后拒绝后续发布，保留诊断；`detach()`须在推理结束后恢复原有方法并释放来源索引。

事件中的采样位置来自真实账本，padding单列；时间使用当前进程单调时钟。正文与进度的原子Context接入属于NTF-017／020。调用失败后封装停止，协调器保留两路进度。

## 验证边界

[契约检查](../../tests/test_native_soulx.md)使用实际官方方法和轻量CPU依赖，将同PCM、种子与配置下的未插桩调用作为参照，比较音频、ASR、LLM输入、修订／反馈、服务结果和reset数值。该检查不代替NTF-018／019的真实权重远端对照。
