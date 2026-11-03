# 远端工作目录约定

更新：2026-11-03。项目现名为 ParaThink。下表中的 `InterClarify`、`interclarify-*` 是已有服务器目录或环境的真实名称，继续保留以兼容现役资产；本仓库不执行远端仓库或目录重命名。

根目录为 `/hpc_stor03/sjtu_home/xuan.zhang/`。远端只保留当前源码、模型、数据、现役 conda 环境与评测入口；运行输出使用独立目录，不覆盖既有结果。

## 1. 目录与资产

| 位置 | 用途 |
| --- | --- |
| `InterClarify` | 当前项目仓库 |
| `xtalk` | X-Talk fork 源码 |
| `DuplexCascade` | 官方 DuplexCascade 参考仓库 |
| `interclarify-p0-models` | Qwen2-7B、DuplexCascade 权重与 HF 辅助资产 |
| `interclarify-asr-selection/models` | Nemotron 与 alignment 资产 |
| `interclarify-tts-selection-20261018/models` | Kokoro 模型 |
| `interclarify-english-integration-20261018-v1/envs` | 现役 ASR/TTS conda 环境 |
| `interclarify-english-integration-20261018-v6` | 组件入口；`envs` 软链到 v1 |
| `interclarify-runtime-20261021-adopted` | 当前运行时源码快照 |
| `interclarify-runtime-current` | 指向当前运行时快照的稳定入口 |
| `InterClarify/benchmark/fdb_v1_0` | FDB v1.0 评测数据 |
| `Full-Duplex-Bench` | 官方 FDB 评分仓库 |
| `parathink-soulx-duplug` | 前端独立部署与检查根目录，复用下列资产；见[部署说明](dev/SoulX-Duplug/deployment.md) |
| `parathink-soulx-duplug/upstream/soulx-duplug` | 官方 SoulX 源码，独立 Git checkout，提交 `a0b9063` |
| `turncontrol-comparison/models/soulx-duplug` | 复用 SoulX tokenizer、基座和状态权重，不复制或修改 |
| `turncontrol-comparison/models/sensevoice-small` | 英文 SenseVoice 权重，只读复用 |
| `turncontrol-comparison/models/x2streaming-asr` | 独立 X2Streaming-ASR 权重，只读复用 |
| `turncontrol-comparison/upstream/frozen-20261028/x2streaming-asr` | X2 官方推理源码，只读复用 |

## 2. 固定 conda 环境

| 用途 | 环境 |
| --- | --- |
| 通用与模型服务 | `~/miniconda3/envs/interclarify-dev` |
| FDB 官方评分 | `~/miniconda3/envs/full-duplex-bench` |
| ASR 组件 | `~/interclarify-english-integration-20261018-v1/envs/asr` |
| TTS 组件 | `~/interclarify-english-integration-20261018-v1/envs/tts` |
| SoulX 与 SenseVoiceSmall | `~/turncontrol-comparison/envs/soulx`，只读复用，不修改共享依赖 |

`paratalker-dev` 与 `sidecar` 属于其他项目，不纳入 ParaThink 清理。

## 3. 当前前端结果

| 记录 | 证据与状态 |
| --- | --- |
| 完整预热与三轴预检 | `parathink-soulx-duplug/runs/ntf018-matrix-20261103-r3`，3/3 完整、退出 0，见[报告](../docs/reports/soulx/20261103-ntf018-warmup/README.md) |
| 固定 FDB30 验收 | `parathink-soulx-duplug/runs/ntf019-dual-20261103-r2`，用户审核通过并归档，见[报告](../docs/reports/soulx/20261103-ntf019-fdb30/README.md) |
| 取消 800ms 停止条件 | 单／双路与分析器修订，169 项本地检查通过，见[记录](../docs/reports/soulx/20261103-latency-limit-removal/README.md) |

历史 run、日志和原始产物保留在远端或本地 `artifacts/`，不作为当前路线入口。

## 4. 运行约定

- 会话、模型与环境使用 conda；模型和 conda 环境按只读方式复用，不复制权重。
- 每个作业使用独立 `run_id` 与输出目录，保留源码提交、输入摘要、资源上限、退出码和失败日志。
- 维护操作串行执行，优先同文件系统 `rename`，避免复制大模型或音频，也不做无界整盘扫描。
- 删除或迁移前先核对当前作业、磁盘/内存配额和其他项目。
- 当前运行快照与稳定入口之间的映射在任务单中登记，作业运行期间不得删除对应源码。
