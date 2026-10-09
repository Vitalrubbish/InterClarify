# 任务单：P0 路线重置后集群环境验收

## 目标

在远端 RTX 4090 集群上重新验证 X-Talk 路线的通用基础设施：

1. conda 环境能导入当前 P0 固定依赖并识别 GPU；
2. 配置和 manifest 正确记录固定的 X-Talk 来源，不再包含旧底座字段；
3. 同一离线输入在相同配置下产生结构一致的日志；
4. 保存镜像 digest，为 P1 核验 `xtalk:v0.17` 与源码提交的对应关系提供输入。

本任务不安装 X-Talk、不下载模型，也不声称完成 P1。

## 前置条件

- 使用由当前 `scripts/remote/Dockerfile.p0` 构建的新镜像标签，禁止覆盖旧标签；
- 仓库已同步到共享存储并记录干净提交；
- `docs/p0/xtalk_registry.md` 已固定候选源码提交；
- `pdgpu-4090` 配额可用。

## 资源

| 项 | 值 |
| --- | --- |
| 队列 | `pdgpu-4090` |
| GPU | 1（只验证可见性） |
| CPU / 内存 | 8 核 / 32 GB |
| 任务数 | 1 |

## 执行

```bash
bash scripts/remote/submit_p0_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

证据目录：

```text
/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p0_env/<时间戳>/
```

## 验收清单

1. `env.json` 中 `status=PASS`、`missing_core=[]`、`gpu.cuda_available=true`；
2. `audio_io.json` 有结果，headless 节点允许 `status=NO_DEVICES`；
3. 两次 smoke 的事件类型序列和 `metrics.json` 相同；
4. smoke 的 `manifest.json.model.repo_url` 为 `https://github.com/xcc-zach/xtalk`；
5. `git.txt`、镜像标签和镜像 digest 已归档；
6. 结果回填 [docs/p0/README.md](../p0/README.md)。

## 历史结果说明

2026-10-07 的 P0 作业证明旧配置下的通用脚手架能在 4090 节点运行，但其依赖集合、24 kHz 配置和 manifest 底座字段已经失效，不能作为本任务的验收结果。

## 失败处理

- 环境导入失败：核对新 `requirements.txt` 与镜像构建日志；
- 无 GPU：检查队列配额和 `--gpu-per-task`；
- manifest 仍出现旧字段：检查配置与 `build_manifest`；
- 日志不一致：保留两份运行目录并定位非确定性字段；
- 镜像无法映射到 X-Talk 源码：在 P1.0 标记为阻塞，不以标签猜测版本。
