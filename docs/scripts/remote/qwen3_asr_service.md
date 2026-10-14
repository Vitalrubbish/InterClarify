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
- `SessionState`：一个会话的流式解码状态、串行锁，以及上一次的已解析转写 `last_parsed` 与已交给调用方的 `visible_text`。
- `truncate_tokens(model, text, token_count)`：把已解析转写去掉末尾 `token_count` 个 token（并对 `\ufffd` 做与解码器一致的收缩），得到解码器**不会再改**的前缀。
- `advance_committed(model, state, token_count, last_parsed, visible_text)`：有新文本时给出上述前缀；本次解码没有新增文本时给出完整转写（释放被扣住的尾巴）。两种情况都要求候选延长 `visible_text`，否则整拍保持不变。
- `ASRService`：加载一次模型，维护 `session_id → SessionState`。`create_session` 用 `init_streaming_state` 建状态；`recognize` 把 base64 解码为 `float32` 交给 `streaming_transcribe`；`delete_session` 释放。
- `build_app(service)`：构建 FastAPI 应用，把四个端点绑定到服务。
- `main`：解析参数（模型路径、host/port、显存占用、max_new_tokens、`chunk_size_sec`/`unfixed_chunk_num`/`unfixed_token_num`、`--emit-committed-prefix`），加载模型后 `uvicorn.run`。

由 `run_xtalk_round1.py serve asr` 在 ASR 环境内启动，参数取自首轮配置的 `services.asr` 与 `asr_streaming`。

## 两种返回语义

`qwen_asr` 的流式解码每块都会**回滚上一轮末尾 `unfixed_token_num` 个 token 后重解**，因此原始 `state.text` 可能替换已经发出过的文字。官方 DuplexCascade 从不面对这种情况（`server.py` 的 `stt_receiver_task` 只收 `type == "Word"`，注释写明 `# ignore Step / EndWord / Marker`），它拿到的是**已定稿的词流**。本服务因此提供两档：

| 档位 | 触发方式 | `is_final=false` 返回 | `is_final=true` 返回 |
| --- | --- | --- | --- |
| 原始转写（历史行为） | 不加 `--emit-committed-prefix` | `state.text`（含易变尾巴） | `state.text` |
| 定稿前缀（推荐） | `--emit-committed-prefix` | 见下方两条规则 | `state.text` 全量释放，并作为后续推进的基点 |

定稿前缀下的两条规则：

- **有新文本**：返回"已解析转写去掉末尾 `unfixed_token_num` 个 token"的前缀——这段是解码器承诺不会再改的部分，因此模型不会拿到"用户还没说完的版本"。
- **本次解码没有新增文本**（停顿、静音、句子结束）：直接返回完整已解析转写，把上一拍扣住的尾巴**释放**。否则句尾那 2–3 个词会在用户说完后永久缺失（第一次实现就是如此：`synthetic_user_interruption/1` 的最后一拍只有 `… Actually, what are some financial`，`goals I should set?` 再没出现）。释放时机对应官方 Kyutai 词流提交这些词的时刻。

无论哪条规则，返回的文本**只会变长**：候选不以上一次给出的文本为前缀就整拍保持不变。

**截断作用于已解析转写（`state.text`），不是原始解码串（`state._raw_decoded`）**。这是必须写死的一条：原始串形如 `language English<asr_text>…`，若按 token 从**原始串**末尾截断，截断点落在 `<asr_text>` 之前时就会把 `language English` / `language` 当作用户文本交给模型——第一次实现正是如此，`replay` 的 normal 场景里模型连续 397 拍只输出 `<|user is talking|>`、`response_ids` 为空（模型看到"用户"在说 "language"）。`state.text` 已经去掉标签，因此不再可能泄漏。

注意 `is_final=true` **不重置**已提交文本：它把 `last_parsed`/`visible_text` 直接设为全量转写，因此下一次响应仍然只会追加。这与运行时的语义一致——X-Talk 在用户停顿（`is_final_chunk`）时就会发 `is_final=true`，所以尾巴并不会被藏到会话结束。

配置入口：`configs/xtalk_round1.yaml` 的 `asr_streaming.emit_committed_prefix`（配合 `unfixed_chunk_num: 0`，让每个 chunk 都基于携带前缀，从而保证"已定稿前缀"本身单调）。契约与证据见 [阶段 A 任务单 §9.5](../../xtalk_a4_remote_acceptance.md)。
