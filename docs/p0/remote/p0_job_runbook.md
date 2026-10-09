# P0 集群执行 Runbook

本手册配合任务单 [docs/jobs/p0_environment_check.md](../../jobs/p0_environment_check.md) 使用，固定镜像、环境与操作步骤。

## 环境总览

| 组件 | 版本/来源 | 位置 |
| --- | --- | --- |
| 基础镜像 | `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk:v0.17` | CUDA 12.8.1 / Python 3.11 / torch 2.9.1+cu128 |
| P0 镜像 | `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2` | 由 [Dockerfile.p0](../../scripts/remote/Dockerfile.p0.md) 构建 |
| conda 环境 | `interclarify-dev`（Python 3.10） | 镜像内 `/opt/conda/envs/interclarify-dev` |
| 仓库 | `Vitalrubbish/InterClarify` | 共享存储 `/hpc_stor03/sjtu_home/xuan.zhang/InterClarify` |
| 证据产物 | 本次作业输出 | `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p0_env/<时间戳>/` |

## 固定路径

- 仓库：`/hpc_stor03/sjtu_home/xuan.zhang/InterClarify`（与开发机 `/mnt/cloudstorfs/...` 同一份工作区）；
- 模型根（P1 使用，本阶段不下载）：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models`；
- 产物根：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts`。

## 构建镜像

```bash
docker build -f scripts/remote/Dockerfile.p0 \
  -t docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2 .
docker push docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2
```

registry 不允许覆盖已有 tag；修改依赖或代码后递增版本（`v0.2`、`v0.3` …）。

## 提交流程

```bash
# 确认工作树干净并把提交同步到共享存储
git -C /hpc_stor03/sjtu_home/xuan.zhang/InterClarify status --short

bash scripts/remote/submit_p0_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

## 验收

```bash
ART=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p0_env/<时间戳>
cat "$ART/environment.txt"
python - "$ART" <<'PY'
import json, sys, pathlib
art = pathlib.Path(sys.argv[1])
env = json.loads((art / "env.json").read_text())
print("status:", env["status"], "missing:", env["missing_core"], "gpu:", env["gpu"]["devices"])
def events(run):
    return [json.loads(l)["event_type"] for l in (art/"smoke"/run/"events.jsonl").read_text().splitlines()]
assert events("p0-smoke-a") == events("p0-smoke-b"), "event structure mismatch"
m = lambda r: json.loads((art/"smoke"/r/"metrics.json").read_text())
assert m("p0-smoke-a") == m("p0-smoke-b"), "metrics mismatch"
print("smoke structure consistent")
PY
```

## 已知取舍

- P0 只申请 1 张 4090 验证环境可见性，不加载任何模型权重；P1 才固定 X-Talk 组件并接入 FDB。
- 容器无音频设备，`check_audio_io.py` 预期返回 `NO_DEVICES`；真实设备验证在带麦克风/扬声器的开发机上用 `configs/local.yaml` 完成。
- HF 官方站点不可达；后续选定的 X-Talk 模型若使用 HF，统一走 `HF_ENDPOINT=https://hf-mirror.com`，并在 [../xtalk_registry.md](../xtalk_registry.md) 的后续资产登记中记录访问条件。
