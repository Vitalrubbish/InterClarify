# X2 两帧教师进程

`scripts/remote/x2_teacher_worker.py`在ASR conda中加载一份NTF-011验收过的`X2Engine`，复用模型、首块、language-tag、EOS协议及缓存。启动时验证模型／官方代码摘要，用同一FLEURS音频做两个完整语音预热会话，要求均有文字；就绪文件保留每次时长、输出与音频摘要。

`X2Session`拥有独立UUID、PCM缓冲、解码线程、步序及释放序号。`run()`每次前进1280样本，首帧补200个左侧零样本，后续窗口1680样本；两个真实音频帧形成一个RPC步骤，累计文字只含EOS闭合组。发布时附带两个帧的token序列、实际观察样本数、计算累计时间与组数。EOF窗口补齐只作诊断，未消费的部分帧不回填在线Context。

`publish()`最多前瞻4个160ms步骤，等待`release()`；释放必须连续且晚于该步解码完成。PCM待处理上限800ms，队列／游标越界明确失败。`poll()`始终区分尚未就绪、空文本完成与线程异常；取消唤醒PCM读取和屏障，`close()`最多等10秒，未退出则拒绝继续复用。

Unix socket沿用create／push／poll／release／close操作，限制单会话、RPC大小与超时。会话结束保留RTF、真实帧数、未发布帧数和峰值显存诊断。
