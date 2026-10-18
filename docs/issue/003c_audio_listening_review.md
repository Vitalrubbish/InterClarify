# Issue 003c：Kokoro 分段试听复核

状态：进行中，待修复包复听。父任务：[003](003_kokoro_playback_integration.md)。

## 已有人工反馈

2026-10-19，评价者为用户。原r4包读法没有问题，但一句话被分成多块、块间不连续，首轮听感未通过；尚无逐文件时间位置，不补造记录。原文件摘要见 [r4试听清单](../../reports/english_integration/20261018-r4/listening_manifest.json)，原结果保留。

## 当前试听包

[003d](003d_segment_continuity.md)已完成代码及远端自动验证，新文件见 [试听报告](../../reports/tts_continuity/20261019/README.md)和 [SHA256清单](../../reports/tts_continuity/20261019/listening_manifest.json)：

- [ ] confirmation.wav：短确认是否自然，nine thirty等读法是否仍正常。
- [ ] clarification.wav：Tuesday/Thursday及9:30/3:15是否清楚，整句接续是否自然。
- [ ] long_answer.wav：句内接续是否改善，辅音起止是否完整，句间停顿是否合适。

micro_turn_supply.wav是正常600ms供给诊断，slow_text_supply.wav刻意供给过慢，后者保留真实断流，不能把它当成修复失败的主三例。人工复听结论未到达前，不将003c/003d或父任务003标为听感通过。
