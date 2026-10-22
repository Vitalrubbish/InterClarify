# X2-Turn 服务诊断客户端

`scripts/remote/x2_turn_service_probe.py` 把一条 WAV 按真实时钟送进打过 overlay 的 vLLM `/v1/realtime`，记录原始 `transcription.delta` 与 `turn.delta` 帧及其接收时刻。它只用于部署阶段证明服务真的输出 ASR 与原生状态头，不承担正式回放、WER 或 complete 输出率统计。

## 协议与计时

- 连接后先收到 `session.created`，随后发送一次 `session.update` 指定模型名。
- 协议只接受单声道 16 kHz 16-bit PCM。固定 FLEURS 输入保留原始 32-bit float 编码，客户端用 `soundfile` 读取后按满量程转换为 PCM16，不重采样、不改声道；原始子类型记入 `probe.json`。
- 音频按 80 ms（1280 采样）切块；每块发送 `input_audio_buffer.append` 后紧跟 `input_audio_buffer.commit`，与作者 smoke 客户端一致。
- 发送按真实时钟排程，记录每块相对计划时间的迟到量；接收在独立协程中进行，每个事件立即打 monotonic 与服务端 UTC 时间戳。
- 音频发送完毕记 `t_end`，继续接收 `--drain-seconds`（默认 5 秒）再关闭。

## 汇总口径

`summarize` 只做诊断口径：

- 统计各事件类型数量、拼接增量转写文本。
- 逐帧保留 `frame_index`、`turn_id`、`turn_class`、`probs`、相对 `t_start` 的接收秒数和是否在 `t_end` 之后。
- 校验 `turn_id` 与 `turn_class` 是否符合原生映射（35 idle、36 noidle、37 speaking、38 turn_end、39 backchannel、40 uncertain），不一致直接报错。
- `complete` 只按 `turn_end`/ID38 统计：是否出现、总帧数、输入结束前后各自帧数、结束后首次命中的相对延迟（未命中为 null）。

该延迟以文件输入末端为参照，是部署诊断值，不是正式测试的分母，也不称语义准确率。

## 使用

```bash
$ENV/bin/python scripts/remote/x2_turn_service_probe.py \
  --url ws://127.0.0.1:18011/v1/realtime \
  --audio "$ROOT/dataset/fleurs_en_us/audio/dev/<file>.wav" \
  --output "$OUTPUT/probe_dev"
```

参数：`--drain-seconds` 观察窗长度，`--chunk-ms` 发送块长（默认 80），`--model` 服务端注册名。

## 输出与失败

- `summary.json`：上述诊断汇总。
- `events.jsonl`：全部原始事件与接收时间戳，可离线重算。
- `probe.json`：输入音频元数据、URL、模型与运行参数。

空转写或没有任何 `turn.delta` 时脚本以非零退出，提示 ASR 头或状态头未生效。它不启动 LLM/TTS，不做门控、平滑或控制器合成。
