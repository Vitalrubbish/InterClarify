# 接口设计：X-Talk 接入本地 Qwen3-ASR 适配器

## 1. 目标与范围

让 X-Talk 运行时用本地 `Qwen/Qwen3-ASR-1.7B` 完成流式识别，替换 DashScope 云端实现。模型推理在独立的 ASR conda 环境（vLLM 0.14.0），X-Talk 客户端在 `xtalk-round1-client` 环境，两者通过明确的模型服务协议 + 客户端适配器解耦。

对应任务单 [xtalk_round1_followup.md](xtalk_round1_followup.md) 的 T2。本轮只做接入与最小链路，不做质量评测或延迟预算。

## 2. 现行 ASR 抽象契约

来自 `xtalk/src/xtalk/models/asr/interfaces.py`（fork 提交 `5f0d995`）：

| 方法 | 约定 |
| --- | --- |
| `recognize(audio: bytes) -> str` | 一次性识别整段音频，返回文本 |
| `recognize_stream(audio: bytes, *, is_final: bool = False, chat_history: str | None = None) -> str` | 增量识别，返回**当前累计文本**；`is_final` 只是“临时边界/冲刷尾部”的解码提示，不重置会话，已识别文本必须保留 |
| `stream_chunk_bytes_hint() -> int | None` | 首选块大小；调用方（`AudioConsumer`）据此攒够字节再调用 |
| `reset() -> None` | 清空本会话识别状态 |
| `clone() -> ASR` | 复制一个共享权重、状态独立的实例（每会话一份） |

异步由基类 `async_recognize_stream` 用 `run_in_executor` 包装同步实现，事件循环不被阻塞；`AudioConsumer` 只调用异步版本。

调用点见 `serving/modules/asr_manager.py`：`AudioConsumer.__init__`/`_reset_states` 调 `reset()`；`pause()` 以 `is_final=True` 做句末临时边界（不结束识别）；`end()` 以 `is_final=True` 结束本轮；每次 publish 的文本都是**累计值**。

## 3. 现有 `Qwen3ASRClient` 的偏差

`qwen3asr_client.py` 现状与契约不符：

1. 入参是 `np.ndarray`，契约是 `bytes`（PCM16 单声道 16 kHz）。
2. `recognize_stream(self, audio, cache, is_final)` 位置参数含 `cache` 字典，且 `is_final` 是位置参数；契约是关键字参数 `is_final`/`chat_history`，无 `cache`。
3. 返回**增量**（`new_increment`），契约要求**累计**文本。
4. 没有 `reset()` / `clone()`；状态放在调用方传入的 `cache`，不是实例内部。
5. 无 `stream_chunk_bytes_hint()`。

## 4. 适配器设计

新增/重写 `Qwen3ASRClient(ASR)`（`@model` 注册，名称 `Qwen3ASRClient`，别名 `qwen3asr_client`），构造参数：

- `base_url`：本地 ASR 服务地址（默认 `http://127.0.0.1:8005`）。
- `timeout`：单次请求超时（默认 15 s）。
- `sample_rate`：固定 16000。
- `chunk_ms`：首选块时长，`stream_chunk_bytes_hint = sample_rate * 2 * chunk_ms / 1000`。
- 其余 `**kwargs` 透传服务端（语言等）。

实例内部状态（每实例即一会话，符合 `clone` 语义）：

- `_session_id`：首次使用时向服务注册得到；`reset()` 释放并置空。
- `_confirmed_text`：最近一次累计文本，用于前缀修订判定。

行为：

- `recognize(audio)` → 新建/复用会话，`is_final=True`，返回最终累计文本。
- `recognize_stream(audio, *, is_final, chat_history)`：把 `bytes` 直接作为 `application/octet-stream` 上送（服务端按 PCM16 解析），返回服务端的**累计**文本；`is_final` 表示临时边界/冲刷，服务端据此可选地 `finish` 尾部但保留会话；`chat_history` 目前忽略（量化为接口兼容，服务端未来可选用）。
- `reset()`：`DELETE /v1/session/{id}` 释放；清 `_session_id`/`_confirmed_text`。
- `clone()`：返回同参数的新实例（不同 session）。
- `close()`/`__del__`：尽力释放会话。

非阻塞：保持同步 `requests.Session`（连接池、快速重试），由基类 `async_recognize_stream` 在 executors 中运行；与 `Qwen3ASRFlashRealtime` 同一模式。

## 5. 模型服务协议（HTTP/JSON）

服务端在 ASR 环境启动，按 `session_id` 保留每会话的 `Qwen3ASRModel.LLM` 流式状态：

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| `POST` | `/v1/session` | `{}` | `{"session_id": str}` |
| `POST` | `/v1/recognize` | `{"session_id", "audio": base64(PCM16LE), "is_final": bool}` | `{"text": 累计文本, "language": str, "revision": bool}` |
| `DELETE` | `/v1/session/{id}` | — | `{"ok": true}` |
| `GET` | `/health` | — | `{"status": "ok"}` |

- 会话首次 `recognize` 时按 `config.asr_streaming`（`chunk_size_sec`/`unfixed_chunk_num`/`unfixed_token_num`）调用 `init_streaming_state`；每次请求把音频解码为 `float32` 交给 `streaming_transcribe`，返回 `state.text`。
- `is_final=True` 时调用 `finish_streaming_transcribe(state)` 冲刷尾部，但**不销毁**会话；后续仍可继续 `recognize`（区分临时 flush 与输入结束由客户端 `reset()` 决定）。
- 会话空闲超时或 `DELETE` 时释放状态与 GPU 上下文引用；多会话各自独立。

## 6. 运行配置

生成一份可实例化的 X-Talk 运行配置（区别于只做模型准备的 `configs/xtalk_round1.yaml`），`asr` 段形如：

```yaml
asr:
  type: Qwen3ASRClient
  params:
    base_url: http://127.0.0.1:8005
    chunk_ms: 600
```

其余 `llm_agent`（`DefaultAgent`，关闭 thinking）、`tts`（`MossTTSRealtime`）、`turn_detector`（`XTurnix`）沿用基线；System Backchannel 关闭。

## 7. 测试计划

离线（fork `tests/`）：

- 伪造 HTTP 传输（monkeypatch `requests.Session.post/delete`），断言：
  - `recognize_stream` 收到 `bytes`、透传 `is_final`，返回服务端累计文本；
  - 会话隔离：两个 `clone` 实例 `session_id` 不同；
  - `reset()` 后重新注册新会话，且后续识别不受旧文本影响；
  - `is_final=True` 后继续 `recognize_stream` 仍可累计（临时边界不重置）；
  - `stream_chunk_bytes_hint()` 与 `chunk_ms` 一致。
- 接口一致性：`Qwen3ASRClient` 不再有 `cache` 位置参数，签名匹配 `ASR`。

远端（集群）：T4 的最小连接检查里，用真实服务跑一段音频，确认识别、回答、播放闭环。
