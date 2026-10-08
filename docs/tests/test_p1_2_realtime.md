# `tests/test_p1_2_realtime.py`

## 作用

P1.2 无头双工 harness 的 CPU-only 测试（不加载模型、不需要音频设备）。覆盖：

- **时钟**：VirtualClock 快进且不睡眠、RealClock 单调、`make_clock` 拒绝未知模式；
- **播放所有者**：VirtualPlaybackSink 的播头推进、自然播完发 `playback_finished`、`stop` 只取消未播尾部且已播头部按字节落盘；
- **场景**：加载与 materialize（时长截断/补零、静音段）、缺音频快速失败、未知 expect 键报错、`load_audio_mono` 多相重采样；
- **客户端端到端**：两个 stub 服务器讲官方浏览器协议——`_RegularAnswerStub`（ASR → finish talking → 2s TTS）验证常规回答与 `frames_sent_while_speaking` 双工证据；`_BargeInStub`（4s 回答在问题段发完后检测插话 → interruption + audio_control stop → 新回答）验证打断停播、取消样本数与恢复倾听；另有同连接 `Reset` 多场景测试；
- **服务进程管理**：`OfficialDuplexServer.build_command` 与 `verify_weight_sha256` 正误路径；
- **期望求值**：从 runner 脚本加载 `evaluate_expectations` 验证 pass/fail 判定。

## 运行

```bash
PYTHONPATH=src python -m pytest tests/test_p1_2_realtime.py
```

依赖 `websockets==12.0`；stub 使用 ephemeral 端口与短时真实 pacing，全部用例约 15s。
