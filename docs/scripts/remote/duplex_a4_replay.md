# `scripts/remote/duplex_a4_replay.py`

2026-10-15 测量修复：summarize_timeline 按 monotonic_timestamp 排序，response_latencies 按 response_id/request_id 匹配回答首 token，缺失关联留 null，不用全会话最早倾听事件代替。response.update 只是已播文本确认，不是首音频或首词。客户端新增带 response_id 的 pcm_received 和 playback_started。FDB 的 --fdb-tail-seconds 默认 5 秒，独立诊断 WAV 保留尾部，官方 WAV 仍严格输入等长。诊断输出存 driver 的 diagnostics 目录，避免被官方递归评分识别。传输成功不证明静默正确，semantic_status 需官方评分。

在已启动的模型服务前创建 X-Talk WebSocket 会话，实时发送真实 WAV，保存播放确认下的 PCM 和 JSONL 摘要。复用 `xtalk_link_check.py` 的登录、服务启动、PCM 加载和输入传输；`A4ReplayClient` 扩展接收与播放模拟，并实现各语义场景。

`TimedPcmCapture` 用静音填补会话时钟中的间隔；`A4ReplayClient._play_audio` 串行确认 PCM，停止时丢弃未播尾部。`_run_interruption` 用两层证据判定打断：事件层要求被打断的 response 收到由 `<|user interruption|>`/`<|user is talking|>` 触发的 reset（`turn.tts_stop_requested` 的 reason），声学层在 reset 后再等 `INTERRUPTION_SETTLE_SECONDS`（1s），要求该 response 的音频字节数不再增长（`interrupted_audio_frozen`）；它不要求同一场景另起回答。`_run_long_session` 在同一会话发送多个真实音频片段，保持累计 ASR；它是持续输入压力 smoke。`_run_pause` 先送第一段、停顿后再送第二段，并记录停顿期间是否已抢先回答；`_run_multi_question` 送入连续两问并等待回答结算。

场景集合为 `normal / interruption / long_session / pause / multi_question`。`--scenario-audio NAME=PATH[,PATH...]` 允许每个场景用各自的请求音频（`pause` 需两个以逗号分隔的路径），未覆盖的场景回退到 `--audio`；`--pause-gap-seconds` 控制停顿长度。`read_timeline` 按实际 session ID 读取日志，`summarize_timeline` 汇总原始 token、response 关联、可测延迟，以及播放证据：`played_text_monotonic`（已播文本按前缀单调增长）、`unplayed_tail_excluded`（`response.finish` 不超过最后一次 `response.update`）、`asr_updates_during_playback` 与 `playback_window`（播放窗口内的 ASR 更新计数）。它还区分两种停止来源：`interruption_stop_response_ids`（打断 token 触发的 reset）与 `teardown_stop_response_ids`（`shutdown`/`cancelled`/错误收尾），后者不能作为打断证据，`stopped_response_ids` 保留全部停止用于诊断。`classify` 严格区分 PASS/FAIL/INCONCLUSIVE。

```bash
conda run --no-capture-output -n xtalk-round1-client env PYTHONPATH=xtalk/src:. \
  python scripts/remote/duplex_a4_replay.py \
  --config configs/xtalk_duplex_runtime.json --out /path/fresh-output \
  --scenario-audio normal=/path/regular_answer.wav \
  --scenario-audio interruption=/path/fdb_sample/context.wav \
  --scenario-audio pause=/path/pause_part_one.wav,/path/pause_part_two.wav \
  --scenario-audio multi_question=/path/two_questions.wav \
  --interruption-audio /path/fdb_sample/interrupt.wav --barge-after-seconds 0.6 \
  --scenario normal --scenario interruption --scenario pause \
  --scenario multi_question --scenario long_session --rounds 30
```

输出必须是新的目录。没有实际 interruption token 时，默认语义未覆盖；`--require-interruption` 将其视为失败。已出现 token 却缺少同一 response 的打断 reset、或 reset 后该 response 仍在产生音频时始终失败。已播文本非单调或 `response.finish` 超出已确认前缀时，所有场景判为 FAIL。

`run_fdb_batch` 对一个 FDB 子集的样本目录做批量推理；`copy_fdb_sample` 复制输入和原始标注，排除旧系统输出；`normalize_wav_duration` 使输出与输入等长。每个样本独立会话，clean 与 overlap 输入成对回放；`--fdb-limit` 限制样本目录数，0 表示全部。模型静默也是合法基准输出，评分由官方 FDB 完成。

```bash
python scripts/remote/duplex_a4_replay.py --config configs/xtalk_duplex_runtime.json \
  --fdb-input-root /path/fdb/subset --fdb-output-root /path/new-outputs \
  --fdb-limit 5 --out /path/new-driver-report
```

`--native` 在 FDB 模式保留原生配置的语义 manager，开启相同 timeline；需先启动原生服务。系统附和配置必须为空。详情见 [A4 任务单](../../xtalk_a4_remote_acceptance.md)。
