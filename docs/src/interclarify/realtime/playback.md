# `src/interclarify/realtime/playback.py`

## 作用

P1.2 的**单一 TTS 播放所有者**。服务端收到的每个 TTS 音频帧都提交给唯一 sink，只有它决定“用户实际听到了什么”。落实工程文档第 2.2 节的约束：已播放音频不可撤销，`stop()` 只取消已提交但未播放的尾部，绝不触碰已播头部。

每个 sink 通过注入的 `emit` 回调产生结构化事件：`playback_started` / `playback_finished`（自然播完）/ `playback_stopped`（被取消），载荷含 `played_samples`、`committed_samples`、`cancelled_samples`，使日志能区分“已提交 TTS”与“已经播放”。

## 主要类

### `PlaybackSink`（抽象基类）

- `commit(pcm)`：服务端 → 所有者的提交入口（24 kHz 单声道 float32）；
- `is_speaking()` / `played_samples` / `pending_samples` / `played_seconds()` / `pending_seconds()`：状态查询，查询时先推进播放头；
- `stop(reason) -> int`：取消未播尾部，返回取消样本数；
- 计数器：`committed_samples`、`cancelled_samples`、`max_backlog_samples`（队列堆积代理指标）。

### `VirtualPlaybackSink`

无头所有者。维护 `pending`（已提交未播）缓冲与播放头；`_advance()` 按时钟流逝把样本从 pending 移入已播头部，并可把**已播头部**逐字节写入 raw float32（headerless）文件（`set_played_path` 切换输出文件），供试听与审计。自然播完发 `playback_finished`；`stop` 丢弃尾部并发 `playback_stopped`。

### `SoundDevicePlaybackSink`

本地开发机所有者，基于 PortAudio（`sounddevice` 懒导入，无 PortAudio 的 headless 机器仍可导入本模块）。`sd.OutputStream` 回调在 PortAudio 线程渲染已提交帧，只有实际渲染的部分计入已播；`stop` 清空待播队列（与浏览器 demo 收到 `audio_control: stop` 后清空 playQueue 同语义）。回调内只更新计数，事件统一由调用线程发出。

## 关键约束与取舍

- 双工证据（发声期间仍在收音频）来自 `commit`/`is_speaking` 的真实时序；虚拟时钟下该证据失真，仅用于控制路径快检；
- 会话级计数器跨场景累计，runner 在每个场景前取基线、场景后报告增量；
- `max_backlog_samples` 是“队列堆积”的客户端侧代理；服务端 `audio_q` 满丢旧行为由官方代码保留，不在此处复刻。
