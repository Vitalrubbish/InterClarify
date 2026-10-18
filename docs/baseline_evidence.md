# 历史底座与证据索引

更新：2026-10-18。本文保留解释当前决策所需的历史来源，当前任务以 [issue 索引](issue/README.md) 为准。历史配置、镜像和 PASS 均不代表 Nemotron + Kokoro 新组合已验收。

## 当前依据

- [ASR 比较结果](../reports/asr_selection/20261016-results/summary.md)：FLEURS 英文 100 条，EN 160ms WER 7.68%，Kyutai 21.97%；正确且可对齐词的估计交付 P50 为 414/713ms。覆盖率不同、一次 EN 预热失败与原始长尾仍需保留，不能推广为目标任务错误率。
- [官方输入对齐](asr_official_input_retest.md)：EN 160ms 五例为 0/5，Kyutai 原样/去标点为 5/5、3/5；正常完成分片审计通过，320ms 分片异常，不能宣称完整 100 条成功。
- [TTS 实测与决定](tts_selection_decision.md)：用户最终指定 Kokoro，已有人工均分 4.48/5，完整文本条件首可听代理 P50/P95 为 439/461ms，不能替代增量文本与打断验收。

## 历史来源

X-Talk 上游基座 `5f0d9959edf1026588246efbed827b078cbb114c`，首次连接提交 `d9303c819c96230e527ea5159e7c74f1b5841a3e`；官方控制服务后续经 fork 独立演进。历史 X2 客户端提交 `48c5952`，X2 源码 `0aca80597bb1399c0be4002de5bc62c0a779c542`、权重 `4c8df16b8d7f8b50c95590c4d7907436ebe4aa08`。新实验须重新冻结实际两仓库提交，不从这些历史值推断当前版本。

Qwen3-ASR 因回写与前缀冻结导致交付停滞而退役，X2 仅作诊断。MOSS 保留为现存脚本的历史依赖，不是当前 TTS 目标。首次连接与历史 headless 回执仅证明服务交付和响应生命周期，不能代替声卡实播质量。

| 运行 | 主要证据与限制 |
| --- | --- |
| `20261015T060611Z` | [报告目录](../reports/duplex_acceptance/20261015T060611Z/)；Qwen/MOSS，接话 TOR 0.80，接话延迟 2.558s |
| `20261015T114708Z-r1` | [报告目录](../reports/duplex_acceptance/20261015T114708Z-r1/)；ASR final 后重建分段；Candor pause TOR 0.40，接话 TOR 0.80、延迟 2.838s；UI TOR 1.00、延迟 2.384s，样本 102 沿用旧话题；judge 改为 gpt-4o，rating 不直接跨轮比较 |
| `20261015T172109Z` | [报告目录](../reports/duplex_acceptance/20261015T172109Z/)；X2 首会话预热问题导致失败 |
| `20261015T180154Z` | [报告目录](../reports/duplex_acceptance/20261015T180154Z/)；X2/MOSS 自动门禁通过，Pause 两子集 TOR 0.00；接话 TOR 0.40、UI TOR 0.80、UI 延迟 3.26s；新话题回答仅 3/5，异步末次接收与真实 EOF 排空仍有缺口 |

Pause 保持沉默是预期行为，不能作为漏答。官方 TOR 不能代替新回答覆盖或话题切换正确率。历史 judge 不同的内容分数不直接比较。历史原始音频、完整日志保留远端，紧凑结果保留 reports，不因文档清理改写。

## 本轮文档清理

删除八份已被新路线取代的根级文档：`asr_measurement_retest.md`、`fdb_latency_diagnosis.md`、`x2streaming_asr_retest.md`、`xtalk_a4_remote_acceptance.md`、`xtalk_baseline_stack.md`、`xtalk_modification_plan.md`、`fdb_subset_retest_plan.md`、`asr_next_step_analysis.md`。其有效要求合并到工程方案、当前决策、对齐证据和 issue，避免继续执行 Qwen/X2/MOSS/Pocket 旧路线。

已跟踪旧文档可从 [清理前固定提交 c614d55](https://github.com/Vitalrubbish/InterClarify/tree/c614d55) 恢复；上一轮未提交的 `asr_next_step_analysis.md` 的建议已合并进当前工程方案与 issue，不宣称它存在于旧提交。脚本和测试仍存在时保留同路径说明。清理仅涉及文档，不删除远端权重、conda 环境、运行结果或 fork 源码。
