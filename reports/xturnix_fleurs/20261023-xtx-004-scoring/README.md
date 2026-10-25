# XTX-004：独立评分与链路估计

2026-10-23。状态：离线评分入口与合成 trace 验证完成；尚未对真实回放执行评分。本报告只证明评分合同，不产生真实 start 延迟、WER、模型质量或链路成绩。

## 结论

- `scripts/remote/xturnix_fleurs_test.py` 新增 `score` 入口。它只读取已保存的回放目录、`status.json`、trace 和冻结 manifest，不访问模型服务、不加载权重、不读取音频。
- `t_asr_last` 取在线阶段最后一次词汇增加或词内补全的客户端接收时刻；仅标点、空白、`post_cutoff` 与 EOF 排空变化不移动锚点。纯回写与空转写分别记为 `asr_rewrite`、`empty_transcript`，主延迟为 null，不回退文件末端。
- 命中按 `[t_asr_last, t_asr_last+5s]` 且受 `online_cutoff` 限制评分，并要求请求按事件序号晚于锚点、输入版本不低于锚点且 token 前缀包含锚点文本；提前、旧前缀、窗外、截止后、乱序与不完整窗口分别记录。
- 全部计划样本保留在分母与 CSV 中；未命中、失败、跳过、缺 trace 和无效 trace 的延迟均为 null，不填 0 或 5,000 ms。
- 命中延迟与 `L_chain_estimated=413.582852ms+L_control` 分栏输出。链路值明确标为采用历史逐词 P50 的估计，不是实测音频末词到 start，也不把历史 P95 与控制 P95 相加。
- 辅助 WER 固定使用 `whisper-normalizer==0.1.12`，在线结束文本与 EOF 最终文本分列；空假设按删除计，运行失败为 null 并报告可评分覆盖。

## 交付文件

| 文件 | SHA256 |
| --- | --- |
| `scripts/remote/xturnix_fleurs_test.py` | `c7b3f31665824f3dc222bbb47c213e16cdd89684657d799cb412e90ae8ca7261` |
| `tests/test_xturnix_fleurs_test.py` | `dc9604a144dbb3dc394cf25f6e7ad981a7f4fc65b0f6c67fbbf8d0b48afe352c` |
| `docs/scripts/remote/xturnix_fleurs_test.md` | `b6e651da85a3a3b1c158651c4c2410a6c4719f4407e3325c7affb3222d890d02` |
| `docs/tests/test_xturnix_fleurs_test.md` | `0fbd642fadd2787227ae5289f9415487cbe334f559cc0b974ebf4563d7c2532e` |
| `configs/xturnix_fleurs_test.json` | `ae121007859ab3d7c6d07d38688082bffb0a6803cda3490b0c8b34f6b111fb43`（未改动） |

配置保持 XTX-002 冻结版本；评分只接受 5 秒主窗口，不新增阈值、声学对齐或模型调用。

## 评分口径

| 项目 | 实现 |
| --- | --- |
| 锚点 | `lexical_transition` 区分 append/completion/rewrite/none；`trace_lexical_summary` 只在 `file_audio`、`tail_silence` 阶段保留最后词汇事件 |
| 主窗口 | `[t_asr_last, t_asr_last+5s]` 截断到 `online_cutoff`；窗口未满只标覆盖不足，不补足时间 |
| 命中 | 锚点后首个 `valid=true` 的 `<|start|>`，接收时间在窗口内，输入版本与 token 前缀包含锚点 |
| 诊断 | 首次原始 start 有符号相对时间、提前/旧前缀/窗外/截止后/乱序计数、回写次数、控制失败与非法动作 |
| 延迟 | 仅命中样本给均值、P50、P95、最大值和样本数；P50/P95 使用线性插值 |
| WER | 参考、在线文本、EOF 最终文本均经固定 normalizer；语料 WER 为总错误数/总参考词数 |
| 链路估计 | `413.582852 + L_control`，仅命中样本；与原始增量分栏，附历史来源与限制 |

## 验收映射

| 验收项 | 证据 |
| --- | --- |
| 词内补全、多 token 同批、仅标点变化与事件序号可手算复核 | `test_anchor_ignores_punctuation_and_post_cutoff_words`；`test_hit_latency_and_historical_chain_are_separate`（120ms 增量可手算）；`test_same_timestamp_is_decided_by_event_sequence`（同时间戳与乱序） |
| 提前/过期 start、窗口两端、窗外/EOF 后与不完整窗口 | `test_miss_categories_and_window_edges`；`test_hit_is_kept_when_the_window_is_incomplete` |
| 空转写、回写、运行失败、无 start 与零命中保留分母和 null | `test_runner_keeps_denominator_wer_and_null_latency`；`test_empty_hypothesis_counts_as_deletions` |
| 参考词数与 WER 标准化口径可复核，参考不进入在线回放 | 评分前校验 manifest 摘要与参考标准化结果；trace header 与快照的 `reference_included=false` 检查 |
| 原始增量与历史常数分栏，534ms 示例计算正确 | `chain_estimated_ms = 413.582852 + L_control`；120ms 用例断言为 533.582852ms，其余样本为 null |

## 本地验证

环境：现有 `interclarify-dev`（项目更名前创建，依赖与当前 `parathink-dev` 约定一致）。

```text
python -m unittest tests.test_xturnix_fleurs_test -v
Ran 17 tests ... OK

python -m unittest discover -s tests
Ran 75 tests ... OK
```

评分测试使用合成 trace 和临时目录，不下载 FLEURS、不加载模型、不访问网络；目录中的 `samples.csv` 与 `summary.json` 只用于核对合同。

## 输出合同

```text
runs/<run_id>/replay/score/
├── samples.csv     # 全部计划样本逐例评分，缺失字段为空
└── summary.json    # 分母、覆盖、命中、延迟、WER、链路估计与输入摘要
```

评分目录默认拒绝覆盖；显式 `--overwrite` 才重写 `samples.csv` 与 `summary.json`。输入快照、状态、manifest 或 trace 摘要不一致时直接失败，不静默重算分母。

## 边界与后续

- 本报告没有真实回放或真实评分证据。真实回放、远端作业入口和 5 条冒烟属于 XTX-005；100 条正式回放与独立评分属于 XTX-006。
- 评分不新增声学末词对齐，不把本项覆盖率称为话轮准确率、FDB TOR 或可听回复延迟。
- 不接入 Layer 1/TTS/播放器，不训练、不调阈值，也不改变唯一播放所有权。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/xturnix_fleurs/20261023-xtx-004-scoring/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
