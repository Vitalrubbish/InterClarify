# 评测结果

更新：2026-10-23。FDB 作为辅助工程与能力评测保留；主动澄清专项 benchmark 另行构建，不能以 FDB 指标替代。

| 验证链 | 最新证据与用途 |
| --- | --- |
| XTurnix 输入冻结 | [XTX-001 数据冻结](xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)：固定 100 test＋1 dev、逐文件哈希与历史 ASR 基线 |
| XTurnix 组件协议 | [XTX-002 协议冻结](xturnix_fleurs/20261023-xtx-002-protocol/README.md)：隔离环境、模型修订、Listen 双动作、去标点与 dev 预热；未运行正式回放 |
| XTurnix 远端冒烟 | [XTX-005 A10 冒烟](xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)：单作业完成预检、dev 1 条、test 5 条、停服评分与清理；5/5 完成、0/5 末端 start，仅作诊断 |
| XTurnix pause 诊断 | [句末 pause 探针](xturnix_fleurs/20261023-pause-token-probe/README.md)：5 条 ASR＋100 条参考＋sanity；句末/中段 pause 均 0 次 start，无 pause 仅 1/100；sanity 中英文问句无 pause 可 start、加 pause 全灭，说明调用格式有效，问题是把话轮模型当端点检测用 |
| XTurnix 首轮来源审核 | [48 会话审核](xturnix_training/20261023-source-audit/README.md)：DailyTalk/SwDA 各 24 个会话，30 个条件候选、18 个歧义；当前可直接冻结记录为 0，非双人人工试标 |
| 完整两轴 | [r4 最终结果](fdb/20261021-full-two-axes-r4/README.md)：319 例回放、官方转写与时序评分完成；Smooth TOR 59/119、平均延迟 1.023 秒，Interruption TOR 160/200、平均延迟 1.183 秒；GPT 相关性待补 |
| 固定子集 | [ASR_R4 子集回归](fdb/20261021-asr-subset-r1/README.md)：历史 25 例固定输入，两轴各 5 例官方对齐与时序评分 |

回放使用 X-Talk `d6dc3bf`、Nemotron EN160、Kokoro `af_heart`、600ms micro-turn、300/1200ms TTS 分段、会话 KV 复用与 `duplex_greedy_v1`。原始 WAV、trace 与完整日志留在远端。

评测脚本位于 `scripts/remote/`：

- `full_fdb_two_axes.py`：完整两轴输入冻结、暂存、回放调度与官方评分。
- `xturnix_fleurs_test.py`：XTurnix 评测的 FLEURS 输入、历史 ASR 基线与后续回放/评分入口。
- `setup_xturnix_env.sh`：XTurnix 隔离环境与模型冻结。
- `fdb_subset_report.py`：固定子集评分与尾窗隔离。
- `duplex_a4_replay.py`：真实音频会话回放与时间线证据。
- `layer1_fdb.py`：25 例子集暂存与回放驱动。
- `run_fdb_llm_judge.py`：官方 judge 工作副本与指标解析。
- `setup_fdb_scoring_env.sh`：评分环境准备。

执行通过不表示模型能力验收通过；GPT 评分未执行的结论保持 pending。
