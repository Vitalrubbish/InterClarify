# `scripts/remote/xtalk_link_check.py`

## 整体作用

T3/T4 的最小连接检查：从运行配置启动 X-Talk 服务（其 ASR/LLM/TTS/turn detector 指向外部模型服务），再以“前端”身份用 WebSocket 驱动一次会话——发送 `vad_speech_start`、按 16 kHz 单声道 PCM16 实时分帧送入一段 WAV、发送 `vad_speech_end`，接收并模拟播放 TTS 音频，记录事件时间线。用于验证真实 ASR→LLM→TTS→播放链路。

两个场景：**顺序**（默认，`--rounds` 轮次依次进行）与 **插话**（`--barge-in`，先起一段长回复、播放中再送入第二段话，要求 turn detector 停止当前回复并让第二次发言完成）。

## 协议依据

客户端协议来自 fork 的 `serving/modules/input_gateway.py` 与 `output_gateway.py`：文本帧是带 `action` 的 JSON，二进制帧是原始 PCM16 音频。服务要求首条消息为 `attach_session`。回放是 headless，用显式 client VAD 事件提供轮次边界，无需后端 VAD 模型。

## 参数与流程

- `--config`：运行配置（默认 `configs/xtalk_round1_runtime.json`）。
- `--audio`：输入 WAV（16 kHz 单声道）。
- `--out`：报告 JSON 路径。
- `--rounds`：轮数（默认 2）。
- `--timeout`：每轮等待 `finish_resp` 的超时（默认 120 s；node job 的 `link` 模式传 240 s，因为“讲一个很长的故事”回复的模拟播放可达 ~2–3 分钟）。
- `--barge-in`：切换到插话场景。
- `--barge-in-audio`：插话用的 WAV（`--barge-in` 必填）。
- `--barge-in-after-seconds`：播放开始后多久送入插话（默认 15 s）。
- `--drop-turn-detector`：仅调试用。启动前从配置移除 `turn_detector`；移除后 `vad_speech_end` 直接收尾、`vad_speech_start` 打断。切换到音频式 TurnSense 后，正常 `link` 不再使用该开关，走真实 turn detector 路径。

流程：`_serve` 在子进程里 `Xtalk.from_config(config).mount_routes(app)` 起 uvicorn；`LinkClient` 先 `/api/auth/login` 取 token，连 `ws://.../ws?access_token=...`。`_send_turn_input` 发送一段 VAD 界定的发言；`_receive` 并发收集 `update_asr`/`finish_asr`/`update_resp`/`finish_resp`/`start_tts`/`stop_tts`/`tts_finished` 与二进制 TTS 音频，并对每个音频块回 `tts_chunk_played`、在 `tts_finished` 时回 `tts_playback_finished`。顺序场景下 `_run_turn` 等到本轮的 `finish_resp`；插话场景下 `_run_barge_in` 先播放 `--audio` 的长回复，等首个音频到达并再等 `--barge-in-after-seconds`，然后送入插话 WAV，等待 `stop_tts` 与“插话后新起并有 `finish_resp`”的回复，报告 `barge_in_stop_observed`、`continuation_finished`、`tts_audio_after_barge_in`。报告含每轮/场景读数与完整事件列表。node job 会校验 `barge_in_stop_observed` 与 `continuation_finished` 均为 true。

## 已知限制

2026-10-11 修复约定：顺序轮次匹配该轮新增 response ID 的完成事件，并要求收到音频；插话匹配被打断响应 A 的 `stop_tts` 与新响应 B 的 `finish_resp`，旧响应 A 的结束不能算 B 完成。超时、服务器 `error`、接收任务异常或关闭均产生 FAILED 报告和非零退出。报告新增逐响应音频字节与是否在 `tts_finished` 前收到音频。

headless 客户端收到音频后立即回执属于模拟播放确认，只验证交付/停止事件链路；它不验证声卡或真实播放队列。回执携带当前 response ID，旧响应完成/停止均保留各自 ID。复测仍使用既有两轮与插话场景，不增加数据采集或复杂性能评测。

- 这是单会话回放；顺序场景各轮依次进行，插话场景是在播放中主动送第二段话（非自然声学全双工）。
- 与 fork 的 `scripts/test.py` 相比，本脚本不含客户端 VAD 模型与延迟分析录音，只做最小连接证据。
