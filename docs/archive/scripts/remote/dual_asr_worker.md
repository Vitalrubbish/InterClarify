# 独立Nemotron解码进程

对应`scripts/remote/dual_asr_worker.py`。复用已核验的`SynchronizedNemotron`以保证本窗口末token在完成回调前可见；没有发布屏障或release RPC，RNNT缓存持续推进。旧教师worker保持原样。

`UnreadAudioBuffer`区分received减consumed的真正未读积压、已读保留窗口和实际PCM字节；分别限制800ms及128KiB。EOF不补静音，完整真实窗口仍可解码，不完整窗口返回结束。`IndependentSession`保留待领取步骤快照，16条／1MiB触限报错，不靠deque覆盖。poll领取确认只清理旧诊断记录，不影响解码是否继续。

PCM诊断记录原生窗口开始请求与获得完整输入的时刻，用于分开等待音频、特征准备和解码计算；这些时间不作为配对依据。

Unix socket只允许一个会话，操作为create、push、poll和close。异常返回错误并由回放方终止该条；取消唤醒音频等待，close等待模型线程退出，不能退出则隔离并终止本作业。warmup仍复用既有原生服务，不进入正式计时。
