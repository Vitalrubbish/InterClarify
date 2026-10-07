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

## 失败处理

- 镜像拉取失败：确认 `docker.v2.aispeech.com` 登录状态与 tag 拼写；
- 环境导入失败：检查镜像内 `/opt/conda/envs/interclarify-dev` 是否完整，必要时重建镜像并递增 tag；
- 无 GPU：检查 `--gpu-per-task` 与队列配额；
- 日志结构不一致：保留两份证据并定位 `RunContext.record` 的确定性字段。
