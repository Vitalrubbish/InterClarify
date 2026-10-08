# `src/interclarify/realtime/client.py`

## 作用

无头全双工客户端，连到未修改的官方 `server.py` 服务，替代浏览器标签页：脚本化音频驱动麦克风流，TTS 帧全部交给单一播放所有者，并把 P1.2 验收证据记录为结构化事件。

## 协议

与官方 `web/client.js` 完全一致：

- 上行：二进制小端 float32 PCM 帧（80 ms @ 24 kHz）、文本 `Reset` / `Done`；
- 下行：JSON `user_asr` / `assistant_text` / `assistant_special` / `audio_control`，二进制 TTS PCM。

## 主要接口

- `connect()` / `close()`：建立连接并启动接收循环；关闭时发 `Done`、排空接收循环；
- `send_reset(settle_seconds)`：场景间发送文本 `Reset` 并等待服务端会话重建（官方服务端会重建 STT 连接并清空音频队列，过早发送会落入 drain 窗口被丢弃）；
- `run_scenario(scenario) -> SessionResult`：在当前连接上跑一个场景（接收任务按连接存活、按场景切换内部状态）；
- `run(scenario)`：单场景便捷入口（connect → run_scenario → close）。

`SessionResult` 汇总：`control_sequence`、`asr_texts`、`assistant_text`、`answer_phase_count`、`backchannel_count`、`barge_in_count`（客户端检测，发声期间发出 `barge_in` 段）、`server_barge_in_count`（服务端在播放中发出 interruption/talking）、`frames_sent_while_speaking`（双工核心证据）、`tts_received/played/cancelled_samples`、`playback_max_backlog_samples`、`send_underruns`、`max_send_gap_ms`、`duration_s`。

## 关键事件

`session_connected` / `audio_chunk_sent`（含 `playback_speaking`，按 `chunk_event_stride` 降频，末帧始终记录）/ `asr_partial` / `micro_turn_decision` / `answer_phase` / `backchannel` / `user_thinking` / `server_barge_in` / `user_barge_in`（含打断时刻的播放头位置）/ `tts_audio_received` / `playback_stop_command` / `send_underrun` / `session_idle` / `session_timeout` / `session_recv_error` / `session_recv_ended` / `scenario_end`。

## 关键约束与取舍

- **所有调度与超时用墙上时钟**（segment 开始、发送 pacing、空闲等待），与 `clock.mode` 无关；时钟只约束播放所有者（见 `clock.md`）。
- 发送 pacing：每帧按 80 ms 实时间隔对齐；帧间隔超预算（默认 120 ms）记 `send_underrun`——音频设备/调度抢占的代理证据；段音频在场景开始前全部预加载，磁盘 I/O 不打断实时流。
- 服务端 `Reset` 时会发空的 `user_asr` 文本（UI 清空标记），客户端按官方 `client.js` 语义丢弃，不计入 `asr_texts`。
- `start_condition.tts_played_min_seconds` 等待有超时保护（默认取 `post_audio_timeout_s`），超时发 `start_condition_timeout` 并继续发送，场景由期望判定，不会死锁；空闲等待发现接收任务提前结束（连接断开/对端崩溃）时立即发 `session_recv_ended` 退出，不空转到超时。
- 空闲判定：收到过 TTS 后静默 `idle_gap_s` 且不在播放；从未收到 TTS 时等 `no_tts_grace_s`（模型可能仍在生成首个回答）。
