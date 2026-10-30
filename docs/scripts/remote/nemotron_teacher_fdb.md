# FDB 教师文字小样本实验

`run_case()` 按80ms真实时钟包持续把相同 PCM16 音频送给 Nemotron，同时保留有限 SoulX 音频缓存；按160ms次序等待 ASR 完成、准备原生音频回看／前瞻、调用教师前端、发布后 release。每条保留外部逐帧 JSONL，检查下一块开始不得早于前块发布。音频 EOF 之后的 ASR 排空不进入在线状态。

`run()` 复用历史30条冻结 manifest，逐文件核对 SHA256；参考与标注仅供离线分析。`load_controller()` 摘要校验只读加载器，并以会报错的空 ASR 替换 SenseVoice 类，确保无第二识别来源。`analyze()` 计算在线及排空 WER、标注边界前后 complete、停顿 complete 和打断 nonidle 延迟，并保存逐样本全文与状态依据。无参考的接话组不计算 WER；状态时序是诊断，不是下游播放成功率。

运行入口和资源限制见[脚本](run_nemotron_teacher_fdb.md)，30条约513.2秒，旧结果保留。
