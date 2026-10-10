# `scripts/remote/xtalk_link_check.py`

## 整体作用

T3/T4 的最小连接检查：从运行配置启动 X-Talk 服务（其 ASR/LLM/TTS/turn detector 指向外部模型服务），再以“前端”身份用 WebSocket 驱动一次会话——发送 `vad_speech_start`、按 16 kHz 单声道 PCM16 实时分帧送入一段 WAV、发送 `vad_speech_end`，接收并模拟播放 TTS 音频，记录事件时间线。用于验证真实 ASR→LLM→TTS→播放链路。

## 协议依据

客户端协议来自 fork 的 `serving/modules/input_gateway.py` 与 `output_gateway.py`：文本帧是带 `action` 的 JSON，二进制帧是原始 PCM16 音频。服务要求首条消息为 `attach_session`。回放是 headless，用显式 client VAD 事件提供轮次边界，无需后端 VAD 模型。

## 参数与流程

- `--config`：运行配置（默认 `configs/xtalk_round1_runtime.json`）。
- `--audio`：输入 WAV（16 kHz 单声道）。
- `--out`：报告 JSON 路径。
- `--rounds`：轮数（默认 2）。
- `--timeout`：每轮等待 `finish_resp` 的超时（默认 120 s）。
- `--drop-turn-detector`：启动前从配置移除 `turn_detector`。配置了 turn detector 时 `vad_speech_end` 只触发暂停，回合结束依赖检测器给出 `<|start|>`；该开关用于 headless 回放验证主链路（无 TD 时 `vad_speech_end` 直接收尾、`vad_speech_start` 打断）。

流程：`_serve` 在子进程里 `Xtalk.from_config(config).mount_routes(app)` 起 uvicorn；`LinkClient` 先 `/api/auth/login` 取 token，连 `ws://.../ws?access_token=...`，随后 `run` 逐轮执行 `_run_turn`；`_receive` 并发收集 `update_asr`/`finish_asr`/`update_resp`/`finish_resp`/`tts_finished` 与二进制 TTS 音频，并对每个音频块回 `tts_chunk_played`、在 `tts_finished` 时回 `tts_playback_finished`。报告含每轮 `response_finished`、`first_audio_seconds`、`asr_final`、`tts_audio_bytes` 和完整事件列表。

## 已知限制

- 这是顺序、单会话的回放，不是并发全双工；`response_finished=false` 时不会判定通过。
- 与 fork 的 `scripts/test.py` 相比，本脚本不含客户端 VAD 模型与延迟分析录音，只做最小连接证据。
