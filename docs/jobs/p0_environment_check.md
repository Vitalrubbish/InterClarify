# 任务单：P0 集群环境验收

## 目标

在远端 8×RTX 4090 集群上，用固定镜像与固定 conda 环境完成 [engineering_implementation.md](../engineering_implementation.md) 第 4.4 节的 P0 验收：

1. 新 conda 环境能导入核心依赖并识别预期 GPU；
2. DuplexCascade 权重可访问，或已明确记录无法访问的条件与替代时间表；
3. 同一离线输入在相同配置下产生结构一致的日志。

## 前置条件

- 镜像 `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.1` 已构建并推送（[Dockerfile.p0](../scripts/remote/Dockerfile.p0.md)）；
- 仓库在共享存储 `/hpc_stor03/sjtu_home/xuan.zhang/InterClarify` 有最新提交；
- 配额可用：`vc info -u` 显示有 `pdgpu-4090` 名额；
- 已按 [duplexcascade_registry.md](../p0/duplexcascade_registry.md) 确认权重访问条件（本任务不需下载权重）。

## 资源与队列

| 项 | 值 |
| --- | --- |
| 队列 | `pdgpu-4090` |
| GPU | 1（仅验证可见性） |
| CPU / 内存 | 8 核 / 32 GB |
| 任务数 | 1 |

## 执行

```bash
# 1. 提交
bash scripts/remote/submit_p0_job.sh

# 2. 跟踪
vc list -j <JOBID>
vc logs -t <TASKID>
```

脚本在容器内执行 [run_p0_node_job.sh](../scripts/remote/run_p0_node_job.sh)，证据写入共享存储：

```text
/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p0_env/<时间戳>/
```

## 验收清单

1. `env.json` 中 `status=PASS`，`missing_core=[]`，`gpu.cuda_available=true`，设备名为 `NVIDIA GeForce RTX 4090`；
2. `audio_io.json` 有结果（headless 允许 `status=NO_DEVICES`）；
3. `smoke/p0-smoke-a` 与 `smoke/p0-smoke-b` 的事件类型序列与 `metrics.json` 相同；
4. `git.txt` 的可复现提交与工作树状态已记录；
5. 上述证据回填至 [docs/p0/README.md](../p0/README.md)。

## 执行结果（2026-10-07）

| 项 | 值 |
| --- | --- |
| 作业 | `job-179136453153150934891-xuan-zhang`（Completed） |
| 节点 | `d6-hpc-gpu-069` |
| 提交 | `57a5c77c6350c0086c5f1a8bccc68dd6336332cd`（工作树干净） |
| 镜像 | `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2`（由该提交的 Dockerfile 构建） |
| 证据 | `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p0_env/20261007T091659Z/` |

验收清单逐项结果：

1. `env.json` `status=PASS`、`missing_core=[]`、`gpu.cuda_available=true`、设备 `NVIDIA GeForce RTX 4090`（sm_89, 23.52 GB）——通过；
2. `audio_io.json` 有结果，`status=NO_DEVICES`（headless，允许）——通过；
3. `smoke/p0-smoke-a` 与 `p0-smoke-b` 事件类型序列一致（17 条，13 个 `audio_chunk_received`），`metrics.json` 相等，内联一致性校验 `PASS`——通过；
4. `git.txt` 仅含提交 `57a5c77c…`（无附加状态行，工作树干净）——通过；
5. 证据已回填至 [docs/p0/README.md](../p0/README.md)。

修复与说明：

- 本机 overlay2 对旧式构建器在 `WORKDIR` 步骤报 `max depth exceeded`，改用 BuildKit（`DOCKER_BUILDKIT=1 docker build …`）成功；同时移除了非必要的递归 `chmod`；
- `run_p0_node_job.sh` 现聚合环境检查、两次冒烟与一致性校验的返回码，任一失败即非零（已用本机包装器模拟冒烟失败验证）；
- 为消除版本漂移，`setup_env.sh` 与 `Dockerfile.p0` 不再 `pip install --upgrade pip`，pip 固定为 `environment.yml` 的 24.0；镜像相应升为 `v0.2`。

> 早期 `job-179136223910414023233-xuan-zhang`（镜像 v0.1，证据目录 `20261007T083841Z`）在提交 `3ba5ae1` 的脏工作树上运行，仅作历史记录，不作为验收依据。

## 失败处理

- 镜像拉取失败：确认 `docker.v2.aispeech.com` 登录状态与 tag 拼写；
- 环境导入失败：检查镜像内 `/opt/conda/envs/interclarify-dev` 是否完整，必要时重建镜像并递增 tag；
- 无 GPU：检查 `--gpu-per-task` 与队列配额；
- 日志结构不一致：保留两份证据并定位 `RunContext.record` 的确定性字段。
