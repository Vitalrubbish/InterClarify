# 任务单：P1.1 官方控制模型离线样例

## 目标

对应 [engineering_implementation.md](../engineering_implementation.md) 第 5.2 节 P1.1 的“固定最小输入并运行原版推理路径”：在 `pdgpu-4090` 上用未修改的官方 DuplexCascade 权重，以薄适配器注入固定文本 micro-turn 序列，运行官方控制 token 生成路径，保存输入、配置、原始输出、GPU 峰值显存和实时因子。

范围为**仅控制模型（LLM）**：真实 ASR/TTS 服务与音频链路属于 P1.2。

## 前置条件

- P1.1 资产已就绪（见 [p1_official_assets.md](p1_official_assets.md)）：DuplexCascade 快照权重 SHA-256 校验通过、基础模型 `Qwen/Qwen2-7B-Instruct` 就位；
- 仓库 `3rd-party/DuplexCascade` 提供官方 `model.py`/`server.py`；
- 镜像 `…/interclarify-p0:v0.2` 含 `interclarify-dev` 环境（torch 2.4.1、transformers 4.44.2、peft、safetensors）。

## 资源与队列

| 项 | 值 |
| --- | --- |
| 队列 | `pdgpu-4090` |
| GPU / CPU / 内存 | 1 / 8 / 32G（队列限制：单 GPU ≤8 核、≤32G） |
| 任务数 | 1 |

## 执行

```bash
bash scripts/remote/submit_p1_offline_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

容器内执行 [run_p1_offline_node_job.sh](../../scripts/remote/run_p1_offline_node_job.sh) → [run_p1_offline_sample.py](../../scripts/run_p1_offline_sample.py)，产物写入 `$ARTIFACT_ROOT/p1_offline/<run-id>/`。

## 验收

1. 运行目录含 `manifest.json`、`resolved_config.yaml`、`environment.txt`、`events.jsonl`、`metrics.json`；
2. `events.jsonl` 每轮有 `micro_turn_generation`，含 `assistant_special`（控制 token）与 `assistant_text`；
3. `metrics.json` 记录 `cuda_peak_allocated_mb`、`total_latency_s`、`rtf_vs_micro_turn`；
4. 权重仍为固定快照（未改动），脚本不访问网络（`HF_HUB_OFFLINE=1`）。

## 已知取舍

- 单卡 4090 需以 bf16 载入（官方默认 fp32 不适用）；这是内存精度选择，不改权重；
- 固定环境中 fast tokenizer 不可用，回退慢速 Qwen2 tokenizer；对相同文本 token id 等价；
- 文本离线没有音频时长，RTF 定义为“总生成耗时 / (micro-turn 数 × 0.6s)”。
