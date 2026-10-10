# `scripts/remote/qwen3_asr_service.py`

## 整体作用

在 ASR conda 环境（vLLM 0.14.0）内启动本地 Qwen3-ASR 流式 HTTP 服务，把官方 `Qwen3ASRModel.LLM` 的流式 API 暴露给 X-Talk 客户端适配器 `Qwen3ASRClient`。会话状态按 `session_id` 隔离，客户端只发送 16 kHz 单声道 PCM16 字节并读取累计文本，模型推理与 X-Talk 客户端环境保持隔离。

## 协议

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{"status": "ok"}` |
| `POST` | `/v1/session` | `{}` | `{"session_id": str}` |
| `POST` | `/v1/recognize` | `{"session_id", "audio": base64(PCM16LE), "is_final": bool}` | `{"text": 累计文本, "language": str}` |
| `DELETE` | `/v1/session/{id}` | — | `{"ok": true}` |

## 类的设计

- `RecognizeRequest`（pydantic）：一次增量识别请求体。
- `SessionState`：一个会话的流式解码状态加串行锁。
- `ASRService`：加载一次模型，维护 `session_id → SessionState`。`create_session` 用 `init_streaming_state` 建状态；`recognize` 把 base64 解码为 `float32` 交给 `streaming_transcribe`，`is_final=True` 时调用 `finish_streaming_transcribe` 冲刷尾部但**保留会话**（区分临时边界与输入结束由客户端 `reset()` 决定）；`delete_session` 释放。
- `build_app(service)`：构建 FastAPI 应用，把四个端点绑定到服务。
- `main`：解析参数（模型路径、host/port、显存占用、max_new_tokens、`chunk_size_sec`/`unfixed_chunk_num`/`unfixed_token_num`），加载模型后 `uvicorn.run`。

由 `run_xtalk_round1.py serve asr` 在 ASR 环境内启动，参数取自首轮配置的 `services.asr` 与 `asr_streaming`。
