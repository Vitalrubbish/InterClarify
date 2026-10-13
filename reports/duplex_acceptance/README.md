# 全双工运行时验收报告

本目录保存阶段 A 全双工运行时验收的**关键证据**，纳入 git 跟踪；体积较大的原始产物（逐场景 WAV、服务原始日志）留在 `data/runs/`，不进入仓库。

## 目录结构

每次集群运行对应一个 `reports/duplex_acceptance/<UTC-tag>/` 子目录，由 `scripts/remote/run_xtalk_duplex_a4_node_job.sh` 自动复制：

```
reports/duplex_acceptance/<UTC-tag>/
├── source_check.json        # 源码清单校验结果
├── environment.txt          # 各 conda 环境与关键依赖版本
├── git.txt                  # 根仓库与 X-Talk 的提交与状态
├── model_health.json        # 官方权重 health（token ID、checkpoint、dtype、context_length）
├── steps.jsonl              # 逐步状态（PASS/FAIL/INCONCLUSIVE/BLOCKED）
├── a4_summary.json          # 汇总状态：steps、fdb_axes（各 FDB 轴状态）与 replay 紧凑概览
├── gpu_samples.csv          # 显存与利用率采样
├── resource_samples.csv     # 各服务进程组 RSS 采样
├── replay/
│   ├── summary.json         # 真实音频回放总览
│   └── <scenario>_report.json
└── tests/
    ├── a1.log               # A1 回归
    ├── a2_a3.log            # A2/A3 回归
    ├── a4_driver.log        # 驱动与模型服务测试
    ├── fdb_scoring_*.log    # FDB 对齐与评分日志、评分环境固化日志
    └── fdb_scoring_*.json   # 评分汇总与逐样本 rating
```

## 判据

- `PASS`：该步骤门禁通过；`FAIL`：执行或协议失败；`INCONCLUSIVE`：语义场景未覆盖；`BLOCKED`：所需资产或评分环境缺失。
- `a4_summary.json` 只有在所有步骤 `PASS` 时才为 `PASS`；`DUPLEX_A4_REQUIRE_COMPLETE=1` 时非 `PASS` 会返回非零。
- 自动步骤全通过也不等于完整验收：人工试听、资源趋势与原生对照等仍见 [任务单](../../docs/xtalk_a4_remote_acceptance.md)。

## 说明

- 本目录的 `*.log` 与 `*.jsonl` 由 `.gitignore` 显式加例外，覆盖全局忽略规则。
- 请勿手工放入大文件（音频、模型权重）；只保留可供复核的文本证据。

## 姊妹目录：`reports/duplex_marker_probe/`

阶段 A4 的 `user_interruption` 低分诊断需要判断"模型为什么不吐 `<|user interruption|>`"。该诊断用纯文本重放（不占音频链路），产物独立归档在 `reports/duplex_marker_probe/<UTC-tag>/`，任务单与判读标准见 [DuplexCascade 标记探针任务单](../../docs/xtalk_duplex_marker_probe.md)。两个目录都在 `.gitignore` 里对 `*.log` / `*.jsonl` 加了例外。

| Tag | 变体 | 结论 |
| --- | --- | --- |
| `20261013T111116Z` | `raw` / `strip` / `strip_lower` / `burst` | 打断判定会被文本形态确定性翻转，但没有任何变体构成修复 |
| `20261013T111925Z` | `raw` / `strip_lower` / `burst`，各重跑 2 次 | 重复之间逐标记完全一致 → 差异是文本驱动的真实效应，非噪声 |
| `20261013T121244Z` | `raw` / `truth` / `truth_punct`（FDB 真值句子替换 ASR 流） | 真值词流也不构成修复，且翻转方向两边都有 → ASR 用词/标点/粒度这一整类解释被排除 |

## `data/runs/` 保留策略

`data/runs/` 只保留**仍是凭据**的原始产物，其余在验收归档后清理：

- 保留当前被索引的 run（`20261013T070801Z`）：FDB 样本音频（评分输入）、`logs/`、`services/`、`runtime_smoke/`、根级 json/csv、各轴 `fdb_summary.json` 与回放场景 WAV（供人工试听）。
- 保留仍被文档引用的历史 run（如基线验收 `20261011T054900Z`，[基线栈文档](../../docs/xtalk_baseline_stack.md)所引且本目录无副本）。
- 删除已被后续 run 取代的旧 run、上游 checkout 工作副本（`fdb_repo/`）、逐帧时间线（`*/timelines/`）与零字节日志；这些内容或可从 `reports/` 的紧凑副本复核，或不承载结论。
- 环境修复类日志按内容命名归档到 `tests/fdb_scoring_*.log`，而不是留在 `data/runs/` 顶层。

## 运行索引

| Tag | 作业 | 回放场景 | FDB 推理 | FDB 评分 | 汇总 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `20261013T024524Z` | job-…-xuan-zhang | 4/5 PASS（normal、interruption FAIL） | 4/5 轴 PASS | SKIPPED | FAIL | 打断判据误把收尾停止当证据；长历史触发 CUDA OOM |
| `20261013T070801Z` | job-179187528229476527799-xuan-zhang | 5/5 PASS | 5/5 轴 PASS | 作业内 SKIPPED；独立入口补跑 `user_interruption`（rating 0.6 / TOR 1.0 / latency 1.536s） | INCOMPLETE | 完成官方状态机对齐；`interrupted_audio_frozen=true`；OOM 与 model_service_error 计数为 0；评分归因见任务单 §9.2 |

