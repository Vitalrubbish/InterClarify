# P1.1 离线样例证据

本目录保存 P1.1「官方控制模型离线样例」的**小型运行证据**，用于回归对照。按项目约定，`experiments/` 默认忽略，仅本目录在 `.gitignore` 中显式豁免；其它实验产物（`*.jsonl`、大文件等）仍不入库。

## 运行

- 作业：`job-179138919006004209910-xuan-zhang`（`pdgpu-4090`，节点 `d6-hpc-gpu-069`）
- 提交：`cccd84748281a542edb7be67fa35f132d69e6984`（工作树干净）
- 生成命令：`bash scripts/remote/submit_p1_offline_job.sh`
- 说明：任务单 [docs/jobs/p1_offline_sample.md](../../docs/jobs/p1_offline_sample.md)

## `ic-20261007T160632-93c97783/`

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | `run_id`、profile、seed、`git_commit`、`git_dirty=false`、config digest、设备 |
| `resolved_config.yaml` | 实际生效的 `cluster` 配置（含固定 DuplexCascade 版本） |
| `events.jsonl` | `run_start` / `micro_turn_generation` ×4 / `run_end`；含控制 token、文本、token id、延迟 |
| `metrics.json` | `rtf_vs_micro_turn`、`cuda_peak_allocated_mb`、逐轮摘要 |
| `environment.txt` | 主机/解释器/GPU 快照 |
| `node.log` | 容器内运行日志 |

## 关键结果

```text
[1] "Hello"                         -> <|user is talking|>
[2] "how are you today"             -> <|user is talking|>
[3] null (静默)                      -> <|user finish talking|> + "As an AI, I don't have feelings,"
[4] "could you tell me a short joke"-> <|user interruption|>
cuda_peak_allocated_mb=17178.66  rtf_vs_micro_turn=0.4546
```

完整原始产物（含作业日志）另存于共享存储：
`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p1_offline/ic-20261007T160632-93c97783/`。
