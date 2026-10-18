# Issue 003c：真实增量 Kokoro 分段试听复核

状态：待办。父任务003。自动验收通过不代表听感与日期读法已由人确认。

2026-10-18 核对：[listening_manifest.json](../../reports/english_integration/20261018-r4/listening_manifest.json)已记录三个 WAV 的 SHA256，但 `human_review_status` 仍为 `pending_issue003c`，仓库未见评价者、问题位置或听音结论。试听材料准备完成，人工验收未完成，保持待办。

试听包位于 `reports/english_integration/20261018-r4/listening/`（音频不入Git，原件保留远端同run）；文本与分段见同目录上级的r4-tts/verification/*.json。包括confirmation、clarification、long_answer；对应真实每50ms追加5字符的分段输入，不能和完整文本试听混称。

- [ ] 短确认是否清楚完整，是否出现碎词、重复或音色跳变。
- [ ] 澄清句中的Tuesday、Thursday、9:30、3:15读法是否正确且容易区分。
- [ ] 长回答跨段韵律、过短停顿、接续和末尾是否自然。

记录评价者、文件SHA256、发现位置与结论；需要改策略时另建修复任务，并重新冻结策略后重测。此项需要实际听音证据，不能用PCM非空或ASR转写代替。完成后归档，并据此关闭003的最后试听项。
