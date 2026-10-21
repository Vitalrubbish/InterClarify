# `scripts/remote/duplex_a4_replay.py`

`A4ReplayClient` 提供默认关闭的`fdb_tail_audio`选项，仅四配置FDB入口启用：原始音频后连续发送5秒记账静音以便流式ASR排出尾词，不将人工边界或未来文本送入模型。报告明确`diagnostic_tail_audio=true`，总发送耗时含该尾窗，而`input_audio_seconds`仍为原始长度。官方WAV仍截断/补齐到原始输入长度，尾窗只保留在独立diagnostics文件；不把尾窗回复计入官方窗口结果。历史调用保持原先只等待尾窗的行为。

时间线汇总：summarize_timeline 按 monotonic_timestamp 排序，response_latencies 按 response_id/request_id 匹配回答首 token，缺失关联留 null，不用全会话最早倾听事件代替。response.update 只是已播文本确认，不是首音频或首词。客户端新增带 response_id 的 pcm_received 和 playback_started。FDB 的 --fdb-tail-seconds 默认 5 秒，独立诊断 WAV 保留尾部，官方 WAV 仍严格输入等长。诊断输出存 driver 的 diagnostics 目录，避免被官方递归评分识别。传输成功不证明静默正确，semantic_status 需官方评分。

在已启动的模型服务前创建 X-Talk WebSocket 会话，实时发送真实 WAV，保存播放确认下的 PCM 和 JSONL 摘要。复用 `xtalk_link_check.py` 的登录、服务启动、PCM 加载和输入传输；`A4ReplayClient` 扩展接收与播放模拟，并实现各语义场景。

`TimedPcmCapture` 用静音填补会话时钟中的间隔；`A4ReplayClient._play_audio` 串行确认 PCM，停止时丢弃未播尾部。`_run_interruption` 用两层证据判定打断：事件层要求被打断的 response 收到由 `<|user interruption|>`/`<|user is talking|>` 触发的 reset（`turn.tts_stop_requested` 的 reason），声学层在 reset 后再等 `INTERRUPTION_SETTLE_SECONDS`（1s），要求该 response 的音频字节数不再增长（`interrupted_audio_frozen`）；它不要求同一场景另起回答。`_run_long_session` 在同一会话发送多个真实音频片段，保持累计 ASR；它是持续输入压力 smoke。`_run_pause` 先送第一段、停顿后再送第二段，并记录停顿期间是否已抢先回答；`_run_multi_question` 送入连续两问并等待回答结算。

场景集合为 `normal / interruption / long_session / pause / multi_question`。`--scenario-audio NAME=PATH[,PATH...]` 允许每个场景用各自的请求音频（`pause` 需两个以逗号分隔的路径），未覆盖的场景回退到 `--audio`；`--pause-gap-seconds` 控制停顿长度。`read_timeline` 按实际 session ID 读取日志，`summarize_timeline` 汇总原始 token、response 关联、可测延迟，以及播放证据：`played_text_monotonic`（已播文本按前缀单调增长）、`unplayed_tail_excluded`（`response.finish` 不超过最后一次 `response.update`）、`asr_updates_during_playback` 与 `playback_window`（播放窗口内的 ASR 更新计数）。它还区分两种停止来源：`interruption_stop_response_ids`（打断 token 触发的 reset）与 `teardown_stop_response_ids`（`shutdown`/`cancelled`/错误收尾），后者不能作为打断证据，`stopped_response_ids` 保留全部停止用于诊断。`classify` 严格区分 PASS/FAIL/INCONCLUSIVE。

```bash
conda run --no-capture-output -n xtalk-round1-client env PYTHONPATH=xtalk/src:. \
  python scripts/remote/duplex_a4_replay.py \
  --config configs/xtalk_duplex_english_runtime.json --out /path/fresh-output \
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
python scripts/remote/duplex_a4_replay.py --config configs/xtalk_duplex_english_runtime.json \
  --fdb-input-root /path/fdb/subset --fdb-output-root /path/new-outputs \
  --fdb-limit 5 --out /path/new-driver-report
```

历史 A4 任务单见[固定快照](https://github.com/Vitalrubbish/InterClarify/blob/c614d55/docs/xtalk_a4_remote_acceptance.md)。


duplex 会话的 `acoustic_vad_enabled=false` 由服务端按连续 ASR 能力确定：禁用声学 VAD 检测与 pause/resume 调度，保持会话级连续 PCM 与每拍文本读取；轮次仲裁由 DuplexCascade 协议执行。

## 2026-10-21 延迟分解观测

A4ReplayClient 报告会话身份与输入单调时钟；在实际播放 PCM 上按 10ms 窗连续30ms超过-45dBFS检测首可听代理，保留原始起点时间，并记录同回复音频播放缺口。取消后只检测实际越过播放边界的样本。此观测为无声卡回放代理，不等于物理发声。原有回复身份、停止与官方输出时长规则保持。
