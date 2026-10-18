# Issue 003c：Kokoro 分段试听复核

状态：进行中，首轮听感未通过。父任务：[003](003_kokoro_playback_integration.md)。

## 用户试听结果

2026-10-19，评价者为用户。用户确认读法没有问题，但一句话被分为多块，块间不连续。读法项通过，句内连贯性未通过；不能以自动供音断流为 0 代替听感通过。尚未提供逐文件或具体时间位置，不补造记录。

试听包对应 `reports/english_integration/20261018-r4/listening/`，原文本及分段见 r4-tts/verification。三个 WAV 摘要以 [listening_manifest.json](../../reports/english_integration/20261018-r4/listening_manifest.json) 为准；该历史清单保留原运行状态，当前反馈以本任务为准。

## 剩余工作

- [x] 收到实际人工试听反馈：读法正常，分段接续不自然。
- [ ] 完成 [003d 分段连贯性修复](003d_segment_continuity.md)，先根据原分段和时间线区分等待断流与独立合成韵律重启。
- [ ] 用修复策略重生成同类真实增量输入，记录新文件 SHA256、策略和延迟，再人工复听确认句内接续。

读法已通过不表示短确认、澄清句、长回答的全部听感条件通过；父任务 003 暂不归档。
