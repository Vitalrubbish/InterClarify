# 原生SoulX控制封装

对应`scripts/runtime/native_soulx.py`。`NativeSoulX`持有官方TurnModel、设备同步函数及内部状态暂存回调，保留SenseVoice教师、门控、文字修订、KV、反馈、完整话轮识别和原生reset。NTF-017已移除active_output／stop_output及前端停止去重；nonidle与其余状态经过同一联合快照，下游按既有唯一输出生命周期处理。

## 类与核心方法

构造时核对16kHz、2560主块、15360回看、640前瞻及英文SenseVoice；拒绝重复所有者。`_Capture`核对官方源码摘要和固定插桩位置，只增加观察与PCM来源登记，不修改子模块。权重加载仍由[加载器](native_soulx_loader.md)负责。

`step(ledger, step_id)`从账本取得2560采样，执行原生process。设备同步、本次服务、reset全部结束后才返回带身份、开始／完成时间、代次、服务来源及实际窗口的回执；取消后完成的计算不返回有效回执。

`capture_state()`在规则后、服务清理前记录原始及有效状态、拒绝原因、控制文字、真实主块／观察边界和state_available_at。回调只向当前160ms暂存器提交，不直接写Context或操作输出。状态可用时间不被稍后的服务结束或联合提交覆盖。

`_get_chunk()`记录主块、回看、前瞻的真实／合成span和摘要；startup／reset首块含640合成采样，真实推进1920。`_reset()`保留原生数值和随机数行为，代次加一，外部游标退回已处理主块；不恢复旧buffer，不清X2正文或全局step_id。

`_observe_recognize()`只记录实际输入与原生返回文字；SenseVoice整轮服务文字不覆盖外部正文。回执将service_state、service_text和model_complete／wait_fallback分别记录，不把speak改写为原生complete。

`pcm_bytes()`按拥有内存的底层数组去重，reserve_pcm在分配前检查4MiB预算。cancel与短暂存回调串行，保留失败诊断；detach须等设备worker结束后恢复原方法。

[原生对照检查](../../tests/test_native_soulx.md)使用真实官方方法与轻量CPU依赖验证协议；真实权重、性能和质量仍留给NTF-018／019。
