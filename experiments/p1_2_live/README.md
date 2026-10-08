# P1.2 实时双工链路：里程碑证据

`ic-20261008T120009-9dac0cd2`（2026-10-08，作业 `job-179146072814769675121-xuan-zhang`，`pdgpu-4090` 2×GPU，节点 d6-hpc-gpu-053）：

- 运行目录原件：`interclarify-p0-artifacts/p1_2_live/ic-20261008T120009-9dac0cd2/`（含 `artifacts/played_*.f32le` 已播音频与官方服务日志）；
- 本目录保存小文件证据（manifest / resolved_config / environment / events.jsonl / metrics.json）；
- 全部 6 个脚本化场景期望通过，双工证据：5 个场景在系统发声期间持续收到用户音频（共 417 帧），打断停播成功（取消未播音频 1.22s 并恢复回答），发送 pacing 零欠 run；
- Kyutai STT/TTS 由作业从共享存储自动拉起（见 `docs/3rd-party/KyutaiServices.md`）。
