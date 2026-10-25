# XTX-005：A10 远端冒烟与作业入口

2026-10-23。状态：受限作业入口在 A10 上完成预检、dev 协议样本、5 条 test 冒烟、停服评分与清理，退出码 0。结果是诊断性的，不并入正式成绩；正式 100 条由 XTX-006 独立回放。

## 结论

- 单个作业完成了数据/模型预检、真实 Nemotron readiness、1 条 dev、5 条 test、停服后的独立评分和退出清理。
- 5 条 test 全部 `completed`，无失败或跳过；dev 1 条也完成。
- 5 条均为主窗口内未命中（`timeout_no_start`），锚点覆盖与完整窗口覆盖均为 5/5；没有提前 start、旧前缀、窗外、截止后或乱序结果。
- 该 0/5 与 XTX-002 dev 协议探针的 Listen 结果一致：FLEURS 朗读句在 Listen 下持续 `keep`，不能据此调阈值或改抽样。正式分母仍按原 100 条执行。
- A10 上 ASR 加载 23.47 秒，服务峰值 RSS 3,111,660 KiB；GPU 峰值 5,972 MiB（24,564 MiB 总显存）；停服有序，无遗留 ASR 进程。

## 作业与冻结版本

| 项目 | 值 |
| --- | --- |
| 作业 | `job-179275399554108539917-xuan-zhang` |
| 节点 / GPU | `d6-hpc-gpu-038` / NVIDIA A10，驱动 570.144，24,564 MiB |
| 时间（UTC） | 19:14:59—19:19:11，退出码 0 |
| 源码提交 | `eba4cd1` |
| 配置 | `configs/xturnix_fleurs_test.json`，SHA256 `ae121007859ab3d7c6d07d38688082bffb0a6803cda3490b0c8b34f6b111fb43` |
| 运行目录 | `~/interclarify-xturnix-fleurs/runs/xtx-005-smoke-20261023-a10-r4` |
| 提交命令 | `XTURNIX_MODE=smoke XTURNIX_RUN_ID=...`，`--partition pdgpu-a10`，8 CPU/32G/1 GPU |

模型复核通过：XTurnix 21 个文件、Nemotron 12 个文件均与锁一致；数据集 `verify-data` 通过。

## 冒烟结果

| 指标 | 结果 |
| --- | --- |
| dev 协议样本 | 1/1 completed，13.337 秒 |
| test 冒烟 | 5/5 completed，0 failed，0 skipped，87.298 秒 |
| 末端 start 命中 | 0/5 |
| 锚点覆盖 / 完整窗口覆盖 | 5/5 / 5/5 |
| 未命中类别 | 5 条 `timeout_no_start` |
| 提前 start、旧前缀、窗外、截止后、乱序 | 均 0 |
| 命中条件延迟 | null（无命中，不填 0 或 5,000 ms） |
| 在线 / EOF WER | 12/120 = 10.0%，两者相同 |
| 平均控制延迟、链路估计 | null（无命中） |

逐例证据在远端 `replay/score/samples.csv`；`replay/score/summary.json` 的分母为 5，未命中不消失。

## 资源

| 项目 | 实测 |
| --- | --- |
| ASR 加载 | 23.47 秒，`warmup_sessions=2` |
| 服务峰值 RSS | 3,111,660 KiB（约 2.97 GiB） |
| GPU 峰值 | 5,972 MiB（约 5.83 GiB），占 24 GiB 的 24% |
| test / dev trace | 761,405 B / 105,556 B |
| 工作盘 | 893.91 → 893.91 GiB 可用 |
| 清理 | `service_stopped_orderly=true`，无遗留 ASR 进程 |

`job_summary.json` 的 `gpu_peak_memory_mib` 在本轮写成 null：解析 `nvidia-smi` CSV 时没有剥离 `MiB` 单位；原始 `gpu_samples.csv` 的峰值为 5,972 MiB。该解析已在 `69b495b` 修正，正式作业使用修正后的入口。

## 失败路径与修正

| 尝试 | 结果 | 原因与修正 |
| --- | --- | --- |
| a10-r1 | 14 秒终止 | `vc` 包装脚本把命令中的字面量 `JOB` 改写为 `$JOB`，`XTURNIX_JOB_MODE` 变成 `XTURNIX_$JOB_MODE`；改用 `XTURNIX_MODE` / `XTURNIX_RUN_ID`（`85cd20e`），并支持 `XTURNIX_PARTITION` |
| a10-r2 | 26 秒终止 | XTX-002 后加载 `turn_pipeline.py` 生成 `__pycache__/*.pyc`，旧校验把它当额外文件；校验忽略 `.cache`、`__pycache__`、`.pyc`，作业设置 `PYTHONDONTWRITEBYTECODE=1`（`c05cb2e`） |
| a10-r3 | 约 2 分钟终止 | 用隔离的 `envs/xturnix`（`transformers 4.57.1`）启动 Nemotron，缺少 `AutoModelForRNNT`；改为现役 ASR 环境（`transformers 5.15.1`）启动服务，XTurnix 仍用隔离环境（`eba4cd1`） |
| a10-r4 | 成功 | 上述修正后的完整冒烟 |

失败尝试的提交日志与 run 目录保留在远端；没有覆盖旧结果。

## 证据摘要

| 文件 | SHA256 |
| --- | --- |
| `job/job_summary.json` | `eab239b2759c01e89e4c285fe546fca4f7d4c4570f6ca3c0f633753ddfa55ec2` |
| `job/health.json` | `84fce138319530c600eb5ae9a00b0c772b90f818667a1890018ab574c3ea0521` |
| `job/limits.json` | `742d567831a052ee14678267d55d1b898f474ed4a259e1e0ba114d4b29cb189c` |
| `job/gpu_samples.csv` | `a63883d40a5813ae44b516d6e83f61a2fd920d3c020e49fc4b7ccbd24faaa3ee` |
| `replay/status.json` | `164dd3cb45ab6554f902147e5e2cc0055595fba25f403c224a54b0e892ea9d13` |
| `replay/score/summary.json` | `793ac7d9a99789a226e30e21dfda100bb63545e4965ec4463506ffb3dde3a336` |
| `replay/score/samples.csv` | `fc5dbd44318095ddf490401858132bb319a29f33c2feffa163513ad951229a54` |
| `replay-dev/status.json` | `11d30219007be871a451d2837d66f9072f4473c67eabfb6b365d7c6e29246ab0` |
| 提交日志 | `ecf83a91cf7b145265a4fb2bf2f173b1c0aee1e336648c9f08593c8afe9dee8f` |

## 边界

本报告只证明作业入口、服务生命周期、协议回放、评分和清理在 A10 上可执行。它不证明 FLEURS 的 start 命中率或模型质量，也不把 0/5 当作正式成绩。A10 的算力与 XTX-002 的 RTX 4090 不同，控制延迟不能跨硬件直接比较。正式 100 条仍按冻结配置独立回放，不做阈值或抽样调整。

入口说明见 [run_xturnix_fleurs_job](../../../docs/scripts/remote/run_xturnix_fleurs_job.md)。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
