# 评测结果

更新：2026-10-22。FDB 作为辅助工程与能力评测保留；主动澄清专项 benchmark 另行构建，不能以 FDB 指标替代。X2-Turn 的 FLEURS 正式测试单独记录在 [X2Q-014 报告](x2_turn_fleurs_evaluation.md)。

| 验证链 | 最新证据与用途 |
| --- | --- |
| X2-Turn FLEURS 正式 | [X2Q-014 报告](x2_turn_fleurs_evaluation.md)：100 条真实模型回放，WER 22.53%，在线末端文本延迟均值 -1,027.86 ms，输入末端 complete 输出率 1.0% |
| X2-Turn 部署 | [X2Q-010 部署](x2_turn_complete/20261022-deploy/README.md)：冻结 vLLM、480 ms delay、dev 协议诊断 |
| 完整两轴 | [r4 最终结果](fdb/20261021-full-two-axes-r4/README.md)：319 例回放、官方转写与时序评分完成；Smooth TOR 59/119、平均延迟 1.023 秒，Interruption TOR 160/200、平均延迟 1.183 秒；GPT 相关性待补 |
| 固定子集 | [ASR_R4 子集回归](fdb/20261021-asr-subset-r1/README.md)：历史 25 例固定输入，两轴各 5 例官方对齐与时序评分 |

回放使用 X-Talk `d6dc3bf`、Nemotron EN160、Kokoro `af_heart`、600ms micro-turn、300/1200ms TTS 分段、会话 KV 复用与 `duplex_greedy_v1`。原始 WAV、trace 与完整日志留在远端。

评测脚本位于 `scripts/remote/`：

- `full_fdb_two_axes.py`：完整两轴输入冻结、暂存、回放调度与官方评分。
- `fdb_subset_report.py`：固定子集评分与尾窗隔离。
- `duplex_a4_replay.py`：真实音频会话回放与时间线证据。
- `layer1_fdb.py`：25 例子集暂存与回放驱动。
- `run_fdb_llm_judge.py`：官方 judge 工作副本与指标解析。
- `setup_fdb_scoring_env.sh`：评分环境准备。

执行通过不表示模型能力验收通过；GPT 评分未执行的结论保持 pending。
