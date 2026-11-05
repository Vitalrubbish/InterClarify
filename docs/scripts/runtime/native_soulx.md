# 原生SoulX控制封装

对应`scripts/runtime/native_soulx.py`。`NativeSoulX`持有官方TurnModel、设备同步函数及内部状态暂存回调，保留SenseVoice教师、门控、文字修订、KV、反馈和原生reset。NTF-053按用户要求默认跳过complete后的完整话轮重识别，等待兜底识别保持。nonidle与其余状态经过同一联合快照，下游按既有唯一输出生命周期处理。

## 类与核心方法

构造时核对16kHz、2560主块、15360回看、640前瞻及英文SenseVoice；拒绝重复所有者。`_Capture`核对官方源码摘要和固定插桩位置，跟踪观察／PCM来源，并只将complete服务分支的一处识别调用交给`complete_text()`；不修改子模块。替换计数不符立即失败。权重加载仍由[加载器](native_soulx_loader.md)负责。

`step(ledger, step_id)`从账本取得2560采样，在实际调用线程的inference_mode内执行process。设备同步、本次服务、reset全部结束后才返回带身份、开始／完成时间、代次、服务来源及实际窗口的回执；额外记录执行线程ID、名称、实际CPU线程数及complete识别策略。取消后完成的计算不返回有效回执。

`capture_state()`在规则后、服务清理前记录原始及有效状态、拒绝原因、控制文字、真实主块／观察边界和state_available_at。回调只向当前160ms暂存器提交，不直接写Context或操作输出。状态可用时间不被稍后的服务结束或联合提交覆盖。

`_get_chunk()`记录主块、回看、前瞻的真实／合成span和摘要；startup／reset首块含640合成采样，真实推进1920。`_reset()`保留原生数值和随机数行为，代次加一，外部游标退回已处理主块；内部缓冲按原生reset初始化，X2正文和全局step_id持续。

`_observe_recognize()`只记录实际输入与原生返回文字；SenseVoice整轮服务文字不覆盖外部正文。回执将service_state、service_text和model_complete／wait_fallback分别记录，不把speak改写为原生complete。

`complete_text()`默认记录`complete_recognition_skipped`并返回空字符串，保留原服务分支的缓冲整理、speak和reset；不调用SenseVoice、不补造识别文字。`skip_complete_recognition=False`仅供显式严格原生对照，仍调用被观测的整段识别。状态预测前的短窗识别和无语音complete拒绝不受此替换影响。正常加载路径固定使用跳过策略；新对照明确允许这一处差异，不能沿用旧完整服务输出的严格等价声明。

NTF-018增加`capture_revision()`，只读记录官方`need_correction`及上一步文字修订结果。可选`profile=True`为音频token编码、投影、ASR和状态计算增加设备同步计时，并保存实际音频token；`_asr`耗时包含门控、SenseVoice和修订，不能与内部SenseVoice耗时重复相加。默认关闭阶段计时；detach恢复被包裹方法。开启插桩的协议等价性继续由同源官方方法对照检查。

`pcm_bytes()`按拥有内存的底层数组去重，reserve_pcm在分配前检查4MiB预算。cancel与短暂存回调串行，保留失败诊断；detach须等设备worker结束后恢复原方法。

[原生对照检查](../../tests/test_native_soulx.md)使用真实官方方法与轻量CPU依赖验证协议；真实权重、性能和质量仍留给NTF-018／019。
