# 独立X2跨conda执行器

对应`scripts/remote/native_frontend_worker.py`，供NTF-018复用既有ASR conda；SoulX和X2不合并依赖，不修改公共环境。

`X2Process`通过私有socketpair启动唯一子进程，独立加载冻结X2权重和源码。`request()`使用串行JSON请求，每条至多256KiB；加载最长等待300秒，后续单次请求最长30秒，外层作业另有总时限。加载失败会关闭子进程；`close()`先终止，5秒未退出再强制收尾。

`RemoteX2`实现双路调度器所需的80ms接口，每次仅发送当前1680采样及span／摘要，不发送未来PCM。回执保持子进程设备同步后的实际可用／完成时间，另记IPC发送、接收及传输开销；本地回调仅暂存到当前批次。取消后拒绝迟到结果，不在取消回调中阻塞等待IPC。

`WindowLedger`核对窗口长度、有限值、来源span长度与PCM摘要，只允许解码器读取已经发送的窗口。`serve()`每次create统一种子42并重置会话；clear清除音频／文字KV、PCM引用、正文、回调、计数及阶段记录，并等待设备完成，常驻权重保留。

`profile_engine()`为真实encode和LM调用增加设备同步计时；DECODE token与EOS来自原引擎，不人工补齐或改写。X2采样／EOS／开放组合同仍由IndependentX2负责。本地检查使用轻量引擎，真实跨conda加载和显存待远端验收。
