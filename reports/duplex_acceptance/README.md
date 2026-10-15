# 全双工运行时验收报告

本目录保存阶段 A 全双工运行时验收的**关键证据**，纳入 git 跟踪；体积较大的原始产物（逐场景 WAV、服务原始日志）留在 `data/runs/`，不进入仓库。

本目录只保留**最新一轮**验收证据（当前为 `20261015T060611Z`，后端 VAD 生效后的四轴复跑，见任务单 §9.7）：更早的轮次（`20261013T024524Z`、`20261013T070801Z`、`20261014T025649Z`、`20261014T033949Z`、`20261015T030514Z`、`20261015T032348Z`、`20261015T040437Z`）已随仓库清理移除，其结论与数字分别记录在任务单 §9.1–§9.7。

## 目录结构

每次集群运行对应一个 `reports/duplex_acceptance/<UTC-tag>/` 子目录，由 `scripts/remote/run_xtalk_duplex_a4_node_job.sh` 自动复制：

```
reports/duplex_acceptance/
├── reference/
│   └── upstream_full_duplex_bench_table.png  # 上游仓库自带的 FDB 结果表（对照用）
└── <UTC-tag>/
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
    ├── fdb_axes_summary.json    # 四轴官方指标汇总（评分口径与方向）
    ├── <axis>_*_fdb_summary.json # 各 FDB 轴推理汇总
    └── tests/
        ├── a1.log               # A1 回归
        ├── a2_a3.log            # A2/A3 回归
        ├── a4_driver.log        # 驱动与模型服务测试
        ├── fdb_scoring_*.log    # FDB 对齐与评分日志
        └── fdb_scoring_*.json   # 评分汇总与逐样本 rating
```

## 判据

2026-10-15 对当前轮次补充了 [停顿与延迟诊断](../../docs/fdb_latency_diagnosis.md) 与 [逐样本分解](20261015T060611Z/latency_diagnosis.json)：解释 Pause Handling TOR 的输出窗口影响，按回答 request/response 分解 STT/UI 延迟，并单列插话停播延迟。原始证据从远端运行目录读取，未重新运行模型。

- `PASS`：该步骤门禁通过；`FAIL`：执行或协议失败；`INCONCLUSIVE`：语义场景未覆盖；`BLOCKED`：所需资产或评分环境缺失。
- `a4_summary.json` 只有在所有步骤 `PASS` 时才为 `PASS`；`DUPLEX_A4_REQUIRE_COMPLETE=1` 时非 `PASS` 会返回非零。
- 自动步骤全通过也不等于完整验收：人工试听、资源趋势与原生对照等仍见 [任务单](../../docs/xtalk_a4_remote_acceptance.md)。

## 说明

- 本目录的 `*.log` 与 `*.jsonl` 由 `.gitignore` 显式加例外，覆盖全局忽略规则。
- 请勿手工放入大文件（音频、模型权重）；只保留可供复核的文本证据。
- **精简策略**：作业在复制证据后自动跑 `scripts/remote/compact_a4_report.py`，把逐拍数组（`events`、`timeline.played_text`、`raw_outputs`/`protocol_tokens`）折成计数与直方图、把 `*_samples.csv` 折成 `*_summary.json`、把超长文本截断。完整原始流留在 git-ignored 的 `data/runs/<tag>/`，本目录只保留判据：状态、错误、id、时延、字节数、标记计数与日志。规则见 [compact_a4_report.md](../../docs/scripts/remote/compact_a4_report.md)。

## `data/runs/` 保留策略

`data/runs/` 只保留**仍是凭据**的原始产物：

- 保留当前被索引的 run（`20261014T033949Z`）：FDB 样本音频（评分输入）、`logs/`、`services/`、`runtime_smoke/`、根级 json/csv、各轴 `fdb_summary.json` 与回放场景 WAV（供人工试听）。
- 保留提交日志目录 `submit_logs/`。
- 删除已被后续 run 取代的旧 run、上游 checkout 工作副本（`fdb_repo/`）、逐帧时间线（`*/timelines/`）与零字节日志；这些内容或可从 `reports/` 的紧凑副本复核，或不承载结论。
- 环境修复类日志按内容命名归档到 `tests/fdb_scoring_*.log`，而不是留在 `data/runs/` 顶层。

## 运行索引

| Tag | 作业 | 回放场景 | FDB 推理 | FDB 评分 | 汇总 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `20261013T024524Z` | job-…-xuan-zhang | 4/5 PASS（normal、interruption FAIL） | 4/5 轴 PASS | SKIPPED | FAIL | 打断判据误把收尾停止当证据；长历史触发 CUDA OOM。证据已移除 |
| `20261013T070801Z` | job-179187528229476527799-xuan-zhang | 5/5 PASS | 5/5 轴 PASS | 作业内 SKIPPED；独立入口补跑 `user_interruption`（rating 0.6 / TOR 1.0 / latency 1.536s） | INCOMPLETE | 完成官方状态机对齐；`interrupted_audio_frozen=true`；OOM 与 model_service_error 计数为 0；评分归因见任务单 §9.2。证据已移除 |
| `20261014T033949Z` | job-179196172460056683595-xuan-zhang | 5/5 PASS | 5/5 轴 PASS | `user_interruption` 独立补跑：rating 2.25 / TOR 0.875 / latency 4.10s | INCOMPLETE（含一条设计上非 PASS 的 `real_audio_replay` 判据） | 方案 B（append-only ASR 输入契约）复检；交付瓶颈定位到 MOSS-TTS 产量，见任务单 §9.6 |
