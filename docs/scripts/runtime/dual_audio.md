# 同源PCM与160ms联合提交

对应`scripts/runtime/dual_audio.py`。NTF-017将016计算屏障扩展为“两路完成→联合提交成功→下一批次”；同源采样合同见[设计第2.2节](../../dev/SoulX-Duplug/independent_streaming_frontend.md#22-ntf-015016采样映射与实现冻结)。

## 类设计

`PCMLedger`保存单份连续16kHz、单声道、单位增益float32 PCM。append拒绝隐式转换、非有限值和幅度越界；window返回副本及真实／合成span，真实前瞻不足时等待输入，仅显式EOF允许右padding。discard_before释放两路后续计算不再需要的采样；输入到达时间独立于调度开始。

`StepBarrier`保存唯一当前批次、身份、全局step_id和取消代次。begin建立当前暂存区；acknowledge拒绝重复、缺失、过期或取消回执。release必须取得本批次已成功提交的快照，随后才递增step_id。reset不改变全局批次。

`DualAudioFrontend`显式持有一个原生控制器、独立X2和已开轮的joint Context。独占两路暂存回调，拒绝调用方预先绑定外部回调；当前批次至多一条状态、两条正文通知及两条进度。默认单worker串行计算，可选择两种顺序，不增加GPU并发假设。

NTF-018 r2后增加可选`concurrent=True`：当前批次用至多一个辅助线程运行一侧，调用线程运行另一侧，每路模型仍只有一个执行者；等待两侧收尾后才能提交。任何一侧异常立即取消，等辅助线程退出后才返回，避免detach与迟到设备结果竞态。默认串行保持；并发不允许越过160ms屏障，也不暂停生产者，GPU资源争用仍照计。

## 核心流程

```python
context.open_user_turn(session_id, turn_id, source='x2_streaming_asr')
controller = load_native_controller(..., session_id=session_id, turn_id=turn_id)
asr = IndependentX2.load(..., session_id=session_id, turn_id=turn_id)
frontend = DualAudioFrontend(controller, asr, context=context)
```

独立生产者按真实时钟持续append_pcm；调度worker调用advance。每批次完成SoulX原生调用和X2两个80ms步，回调仅送_stage暂存；两路回执齐备后publish_joint_batch一次提交。Context失败或校验错误立即终止，屏障不释放。下一批不等待日志或消费者，前端没有同步on_step消费者回调；下游自行读取完整快照，不需要ack。

推理不持生产者锁或Context锁。finish_input仅标EOF；最后不足160ms的批次按实际存在帧数核对，全部源批次结束后advance返回None，不额外drain、补EOS或补complete。取消／close使屏障和话轮关闭，随后关闭两路；原有完整正文与状态不被部分结果覆盖。若极小容量连关闭元数据也无法写入，close_failure单独保存，模型仍停止，原观察保留。

每路未读真实PCM和在线进度上限800ms，总PCM上限4MiB；传输包、拼接、切块、reset及X2窗口在分配前检查，不减速送音、不丢帧。diagnostics保留最后完整批次、失败暂存、两路实际进度、开放组及各路未处理真实采样。

NTF-018新增`realtime=True`构造参数；正式路径默认保持墙钟800ms保护。固定预热单独传`False`，只关闭墙钟积压判断，未读PCM800ms、4MiB、联合提交和生命周期校验仍有效。预热必须逐步供音并使用私有Context，不能将该参数用于正式回放。

advance返回的lane_compute_seconds、wait_seconds、commit_seconds分别描述模型调用、先完成侧等另一侧和提交耗时；保留input_ready_at、started_at、完成／发布／释放时间。消费者通过Context可选读取计时独立测量。日志由调用方在锁外落盘；本模块不接LLM、TTS或真实播放，NTF-020已取消额外等待并归档，已提交complete直接供下游使用。
