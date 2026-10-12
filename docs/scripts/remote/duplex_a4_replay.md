# `scripts/remote/duplex_a4_replay.py`

在已启动的模型服务前创建 X-Talk WebSocket 会话，实时发送真实 WAV，保存播放确认下的 PCM 和 JSONL 摘要。复用 `xtalk_link_check.py` 的登录、服务启动、PCM 加载和输入传输；`A4ReplayClient` 扩展接收与播放模拟，并实现独立打断和压力路径。

`TimedPcmCapture` 用静音填补会话时钟中的间隔；`A4ReplayClient._play_audio` 串行确认 PCM，停止时丢弃未播尾部；`_run_interruption` 检查旧 response 停止，不要求同一场景另起回答。`_run_long_session` 在同一会话发送多个真实音频片段，保持累计 ASR；它是持续输入压力 smoke。`read_timeline` 按实际 session ID 读取日志，`summarize_timeline` 汇总原始 token、response 关联和可测延迟，`classify` 严格区分 PASS/FAIL/INCONCLUSIVE。

```bash
conda run --no-capture-output -n xtalk-round1-client env PYTHONPATH=xtalk/src:. \
  python scripts/remote/duplex_a4_replay.py \
  --config configs/xtalk_duplex_runtime.json --audio /path/request.wav \
  --interruption-audio /path/interruption.wav --out /path/fresh-output \
  --scenario normal --scenario interruption --scenario long_session --rounds 30
```

输出必须是新的目录。没有实际 interruption token 时，默认语义未覆盖；`--require-interruption` 将其视为失败。已出现 token 却缺少同一 response 的停止证据始终失败。

`run_fdb_batch` 对一个 FDB 子集的样本目录做批量推理；`copy_fdb_sample` 复制输入和原始标注，排除旧系统输出；`normalize_wav_duration` 使输出与输入等长。每个样本独立会话，clean 与 overlap 输入成对回放；`--fdb-limit` 限制样本目录数，0 表示全部。模型静默也是合法基准输出，评分由官方 FDB 完成。

```bash
python scripts/remote/duplex_a4_replay.py --config configs/xtalk_duplex_runtime.json \
  --fdb-input-root /path/fdb/subset --fdb-output-root /path/new-outputs \
  --fdb-limit 5 --out /path/new-driver-report
```

`--native` 在 FDB 模式保留原生配置的语义 manager，开启相同 timeline；需先启动原生服务。系统附和配置必须为空。详情见 [A4 任务单](../../xtalk_a4_remote_acceptance.md)。
