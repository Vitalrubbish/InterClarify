# duplex_playback.py

## 功能与来源

从 TurnControlComparison 的 `scripts/remote/duplex_playback.py` 复用，用于 FDB30 半双工完整系统评测。原文件 SHA256 为 `0ed3fb3db8db143cc99c097cb2df2f305e29f9425e31dd2ced912c50ae5ad6b5`。冻结副本随本项目提交，不依赖远端旧运行目录。

## 类与核心方法

`CancellablePlayer` 唯一拥有播放队列、单调墙钟录音及逐帧账本。`enqueue` 有界排队，`cancel` 丢弃未播片段并返回实际播放内容，`_run` 按真实时间播放并支持中断，`close` 补齐静音时间轴并关闭录音。
