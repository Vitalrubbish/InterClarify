# P0 工程准备

本阶段对应 [engineering_implementation.md](../engineering_implementation.md) 第 4 节：建立可在本地开发机与远端 8×RTX 4090 集群重复使用的基础环境，并提前固定实验必须记录的信息。P0 **不复现模型**（那是 P1），只交付环境、配置、清单格式与集群执行脚手架。

## 交付物

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| 固定 conda 环境 | [environment.yml](../../environment.yml)、[requirements.txt](../../requirements.txt) | Python 3.10 + 固定 pip 依赖 |
| 依赖与模型清单 | [dependency_inventory.md](dependency_inventory.md)、[duplexcascade_registry.md](duplexcascade_registry.md) | 版本、来源、访问条件 |
| 三类配置模板 | [configs/](../../configs/)、[docs/configs/README.md](../configs/README.md) | local / replay / cluster |
| 实验清单格式 | [manifest.json 规范](../src/interclarify/manifest.md)、[运行目录规范](../src/interclarify/run.md) | `manifest.json` / `resolved_config.yaml` / `environment.txt` / `events.jsonl` / `metrics.json` |
| 集群镜像与任务脚本 | [scripts/remote/](../../scripts/remote/)、任务单 [docs/jobs/p0_environment_check.md](../jobs/p0_environment_check.md) | Dockerfile.p0 + setup/submit/node |
| 音频 I/O 报告 | [audio_io_report.md](audio_io_report.md) | 采样率、声道、块长、AEC 结论 |

## 本地验收证据（2026-10-07）

环境：conda `interclarify-dev`，Python 3.10.21，torch 2.4.1+cu121。

### 1. 核心依赖导入与 GPU 识别

`python scripts/check_env.py --require-gpu`：

```text
status: PASS
missing_core: []
failures: 0
torch_version: 2.4.1+cu121
cuda_available: True, device_count: 4
gpu0..3: NVIDIA GeForce RTX 2080 Ti sm_75 10.57GB
```

登录/调试节点为 4×RTX 2080 Ti（sm_75）。PyTorch 能正确识别设备，即满足“新 conda 环境能导入核心依赖并识别预期 GPU”。生产队列 `pdgpu-4090` 的 4090（sm_89）可见性由集群作业复核（见下）。

### 2. 离线输入结构一致性

两次相同配置的回放冒烟 `scripts/run_p0_smoke.py --profile replay`：

```text
run_id: p0-smoke-a, p0-smoke-b
config_digest: 390cb82fcb377faf79cd2a1fd832d0234dcaae8682c241f4e72238474cab076d
event sequence (equal): run_start, audio_input_opened,
  audio_chunk_received × 13, audio_input_closed, run_end
metrics.json: 完全相等
```

结论：同一离线输入在相同配置下产生结构一致的日志（事件类型序列与 `metrics.json` 均一致；仅墙钟字段不同，符合预期）。

### 3. 单元测试

`python -m pytest -q`：`11 passed`，覆盖配置合并、清单确定性、`run_id` 唯一性与冒烟结构一致性。

## 集群验收（2026-10-07，pdgpu-4090）

- 任务单：[docs/jobs/p0_environment_check.md](../jobs/p0_environment_check.md)
- 执行手册：[remote/p0_job_runbook.md](remote/p0_job_runbook.md)
- 镜像：`docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2`（digest `sha256:6df80573…`），由提交 `57a5c77` 的 Dockerfile 构建；
- 提交：`bash scripts/remote/submit_p0_job.sh`，作业 `job-179136453153150934891-xuan-zhang`（Completed，节点 `d6-hpc-gpu-069`）；
- 证据：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p0_env/20261007T091659Z/`。

结果：

```text
git.txt:   57a5c77c6350c0086c5f1a8bccc68dd6336332cd（工作树干净，无附加状态行）
env.json:  status=PASS, missing_core=[], failures=0
gpu:       NVIDIA GeForce RTX 4090 sm_89 23.52GB, cuda_available=true
audio_io:  NO_DEVICES（headless，属预期）
smoke:     p0-smoke-a 与 p0-smoke-b 事件序列一致（17 条，13 个音频块），metrics.json 相等
consistency check: PASS (17 events)；run_p0_node_job.sh 最终 rc=0
config_digest: cb6a279b7254194d48552fa06c6169ae1ff31d84e918a624adddc8ba99d2fac1
```

集群证据记录在干净提交 `57a5c77` 上，满足 [docs/jobs/p0_environment_check.md](../jobs/p0_environment_check.md) 的验收清单第 1–4 项。另以本机模拟（`IC_PYTHON` 包装器令冒烟失败）验证：环境检查通过但冒烟失败时 `run_p0_node_job.sh` 返回非零，作业不会误报 `Completed`。

## 已知限制

1. **gated 权重**：DuplexCascade `model_state.safetensors`（约 17.4 GB）需登录 HF 并接受条件；HF 官方站点在集群不可达，统一走 `hf-mirror`。详见 [duplexcascade_registry.md](duplexcascade_registry.md)。
2. **音频设备**：集群与登录节点均无音频外设，真实设备验证在本地 `local` profile 完成；无 OS AEC，P1 需确定软件回声抑制或半双工方案。
3. **ASR/TTS 语言**：官方 Kyutai STT/TTS 面向英语/法语，目标域若需中文，按 [engineering_implementation.md](../engineering_implementation.md) 第 5.1 节允许替换但须先保存官方结果并统一底座。

## 下一步（P1）

按 [engineering_implementation.md](../engineering_implementation.md) 第 5 节：先通过 GitHub 中转同步代码，在服务器准备并校验官方提交与权重（[P1.1 任务单](../jobs/p1_official_assets.md)），再固定最小输入运行原版推理路径，随后拆分 ASR/控制模型/TTS 服务并接入实时双工链路。P0 的配置层、清单与事件日志格式将在 P1 直接复用。
