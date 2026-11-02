# 同源PCM账本与160ms推进屏障

本说明记录016已交付代码。最新NTF-017合同将推进顺序改为两路完成→文本／状态联合写入成功→下一批次，并移除前端专用停止旁路；当前代码尚未迁移。

对应实现：`scripts/runtime/dual_audio.py`，工作单NTF-016。输入合同和原生padding映射见[设计第2.2节](../../dev/SoulX-Duplug/independent_streaming_frontend.md#22-ntf-015016采样映射与实现冻结)。

## 类设计

`PCMLedger`保存单份连续、不可被调用方回改的16kHz单声道float32 PCM。`append()`拒绝隐式dtype转换、非有限值和幅度越界；增益固定1。每个传输包保存源采样区间和摘要，模型窗口独立构造，不将传输包视为160ms模型步。`window()`返回PCM副本和真实／合成span；真实前瞻未到达则不运行，只在明确EOF时添加右padding。`discard_before()`仅释放两路未来计算／reset均不再需要的旧采样。

`StepBarrier`持有唯一当前批次、全局step_id和取消代次。`begin()`冻结源批次、输入实际到达就绪时间与模型调度开始时间；输入就绪取覆盖所需采样的真实包到达时刻，EOF padding取显式EOF时刻，不拿调度开始冒充。`acknowledge()`拒绝错误步号、重复、过期或已取消回执；`release()`必须同时收到两路完成，保存完成时间、屏障等待及释放时间。内部reset不改变该步号。

`DualAudioFrontend`协调一个原生控制器与一个独立X2，要求同session／turn。默认一个调度worker串行执行两路，同一周期内可选择先控制或先ASR；这符合屏障允许串行计算的合同，没有新增GPU并发假设。每个周期X2连续完成两个80ms帧，SoulX完成一次原生调用，才可启动下一周期。

## 核心方法与使用

独立生产者按真实音频时钟持续调用`append_pcm()`，单调度worker反复调用`advance()`。模型执行不持有生产者所需锁；屏障等待不会暂停收音。真实前瞻不足时`advance()`返回None，由调用者等待新包；不可把该返回误当EOF。

```python
controller = load_native_controller(upstream, soulx_assets, sensevoice_assets, run_dir,
                                    on_state=receive_state)
asr = IndependentX2.load(x2_assets, x2_source, x2_config,
                          on_text=receive_text, on_progress=receive_progress)
frontend = DualAudioFrontend(controller, asr)
```

生产者与推进循环由后续远端入口负责。`receive_state/text/progress`须同步、短时返回；推理、日志、网络和消费者等待不能放进这些回调。当前第一帧闭合正文在本步第二帧和另一条路径之前即可交付，complete pending也不参与屏障释放条件。

`finish_input()`只标记EOF。最后不足160ms的批次允许显式padding，只运行仍有真实音频的X2帧，回执标记terminal；缺少任一路完成、失败或取消仍不能放行。全部源批次结束后`advance()`返回None，剩余控制PCM与开放组由`diagnostics()`保留，不额外伪造步骤。

每路未完成真实PCM上限12800采样（800ms），超过上限的传输包在复制前拒绝；总PCM上限4MiB，包含账本和控制器持有的PCM，并在模型拼接、切块／reset及X2窗口分配前预留预算。真实处理进度较到达时钟落后超过800ms同样失败。生产者持续到达和每次推进均检查上限；不通过减速送音或丢帧恢复。`cancel()`／`close()`先在短锁中取消屏障，再在锁外停止两路发布，避免关闭与回调交错死锁；设备工作结束后才能`controller.detach()`。EOF、显式关闭、取消及内部reset彼此独立。

`diagnostics()`保存最后已释放批次、当前未完成屏障、两路实际进度、原生状态／内部事件、正文和未闭合尾部；失败样本由远端入口落盘。该模块没有Context、回答交接、调度提交、LLM或TTS逻辑。
