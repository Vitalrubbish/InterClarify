# X2 在线 ASR 服务

`scripts/remote/x2_asr_service.py` 把官方 X2Streaming-ASR 的在线自适应解码封装成 HTTP 服务，供 X-Talk 的 `X2StreamingClient` 调用。它只使用在线追加路径，显式关闭离线覆盖。

## 为什么需要独立服务

X2 的官方推理是 `AdaptiveSession`：**在线**路径逐帧（约 80 ms）决定 Wait/Emit 并只追加新文字，**离线**路径在停流后对完整音频重新识别并可能覆盖在线文字。项目的不可撤销边界要求已经交付给用户的文本不被回退，所以服务只暴露在线结果；离线识别仅作为独立质量分析，不进入本服务的返回路径。

同时 `finish_async` 是"整个会话结束"操作（关线程、释放状态），不能映射到每次声学停顿。服务把**短暂停顿**表达为一次普通请求（`is_final` 只作为提示），只有真正的流尾（`end_stream`）才调用 `finish_async`。

## X2Service

| 成员 | 作用 |
| --- | --- |
| `__init__(session_factory, language="en", timeout=60)` | 保存会话工厂、显式语言与超时；单进程只允许一个活动会话 |
| `create()` | 新建一个 `AdaptiveSession`，设置语言、`start()`，轮询 `warmup_done` 直到预热完成；预热期间出错或超时即 `abort()` |
| `recognize(request)` | 追加一段 PCM16、返回在线累计文本；`end_stream` 时调用 `finish_async()` 并等待；把模型的 `live_emit/live_done` 事件写入日志 |
| `close(session_id)` | `abort()` 并释放匹配会话 |

设计约束：

- **单活动会话**：官方模型有跨会话共享状态，服务用锁保证同一张 GPU 上只有一个活动 `AdaptiveSession`；第二个 `create()` 返回 409。
- **在线文本直出**：`recognize` 直接返回 `session.live_text`，不做前缀过滤、冲突检测或提交停滞处理——X2 本身是只追加硬提交。
- **会话身份**：每次 `create` 生成新的 `session_id`；后续请求必须匹配，否则 404。
- **输入校验**：base64 PCM16 必须字节数偶数，否则 400。
- **流结束后写入音频**：在 `end_stream` 之后再送音频视为错误。

## HTTP 接口

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| GET | `/health` | `{"status":"ok","backend":"x2","offline":false}`；进程在权重加载完成后才监听端口，所以健康即代表模型已就绪 |
| POST | `/v1/session` | 分配一个独立解码会话，返回 `session_id` |
| POST | `/v1/recognize` | 追加增量 PCM16，返回当前在线累计文本与语言 |
| DELETE | `/v1/session/{session_id}` | 中止并释放会话 |

请求体字段：`session_id`、`audio`（base64 PCM16）、`is_final`（声学暂停提示）、`end_stream`（真正流尾）。

## 日志

- 模型事件：`live_emit` / `live_done` 逐条记录，含 `session_id`、`delivered_monotonic` 和模型自带字段（音频时间与交付时间），用于区分"算法读到多少音频"和"客户端何时收到"。
- 请求记录：`event=x2_online`，含累计音频秒数、当前在线文本、`pause_hint`、`end_stream`。

## 启动入口

```bash
python scripts/remote/x2_asr_service.py \
  --source-root <X2 源码> --model <X2 权重目录> \
  --language en --host 127.0.0.1 --port 8005
```

启动时用 `git rev-parse HEAD` 校验源码是否等于固定提交 `0aca80597bb1399c0be4002de5bc62c0a779c542`，不等则直接失败；随后加载 `voxtral_asr` 权重（`adaptive_latency=True`、`language_tag.require_checkpoint_weights=True`）并 `eval()`。A4 节点作业在 `DUPLEX_ASR_BACKEND=x2` 时以 `conda run -p $DUPLEX_ASR_ENV` 启动本入口，日志写入 `services/asr.log`。

## 边界

- 只服务单会话、单 GPU；不承担并发多路 ASR。
- 不返回离线重识别文本；不回写已交付的在线前缀。
- 语言必须显式传入（FDB 为 `en`），不依赖模型默认语言。
- 本服务的单元测试见 [test_x2_asr_service.md](../tests/test_x2_asr_service.md)。
