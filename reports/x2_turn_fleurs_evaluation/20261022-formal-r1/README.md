# X2Q-014 正式轮逐例产物

2026-10-22。本目录只保存小型评分摘要，不保存音频、原始 trace 或服务日志。

| 文件 | 内容 | SHA256 |
| --- | --- | --- |
| `samples.csv` | 100 条逐例 replay 状态、WER、S/D/I、参考词数、文本延迟、EOF 变化、complete 命中/提前/未出现/帧数 | `a809b6cbda40cfdf7057a253d463a6f7866238bb482e1bcdea42cab597dce575` |
| `report_data.json` | 固定身份、有效配置、资源摘要、ASR/complete 汇总和逐例结构化结果 | `986fc2262435a301b2b5ab5ef12a4bb21196397ffdedecf5fc8f4b2622d3a25d` |

远端原始证据：

```text
/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2-turn-complete/runs/formal-20261022-r1/
```

原始 `000.json`–`099.json`、`asr_scores.json`、`complete_scores.json`、`run.json` 与 `job/` 保留在该目录；报告正文见 [../../x2_turn_fleurs_evaluation.md](../../x2_turn_fleurs_evaluation.md)。

`report_data.json` 的 `samples` 顺序与 `run.json` 的计划顺序一致；`samples.csv` 可直接用于逐例复核。`complete_latency_ms` 只在 `complete_hit=true` 时有值，未命中保持 null，不填 0 或 5000。
