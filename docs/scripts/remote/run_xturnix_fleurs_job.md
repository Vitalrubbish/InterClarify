# XTurnix FLEURS 受限作业入口

`scripts/remote/run_xturnix_fleurs_job.sh` 在一个调度 GPU 作业内串行完成 XTX-005/006 的预检、Nemotron 服务生命周期、真实时钟回放、停服后的独立评分与清理。`scripts/remote/submit_xturnix_fleurs_job.sh` 只按现有 `vc` 方式提交这个入口，不新建通用调度框架。

## 模式

| 模式 | 行为 |
| --- | --- |
| `smoke` | 预检后串行回放 1 条 dev 协议样本和 5 条 test 样本，停止服务后评分；任一样本未完成即失败 |
| `formal` | 预检后串行回放 1 条 dev 协议样本和冻结的 100 条 test 样本，停止服务后评分；逐例失败保留并在汇总中可见 |

dev 样本只用于协议检查，不计入正式分母。正式运行不会因为出现 start 或未命中而调整阈值、抽样或配置。

## 执行阶段

1. **参数与输出**：校验 `smoke|formal`、新 `run_id` 与输出目录；目录非空直接失败，避免覆盖旧证据。
2. **冻结预检**：核对配置 SHA256 必须是 XTX-002 冻结值；运行 `verify-data` 重新校验 101 条输入；运行 `setup_xturnix_env.sh verify` 重新校验隔离环境、XTurnix 逐文件摘要和只读 Nemotron 资产。
3. **资源与端口**：要求工作盘至少 30 GiB 空闲；记录可见 CPU、内存、GPU 型号与显存；ASR 端口已占用时失败。
4. **服务生命周期**：`setsid` 启动冻结的 Nemotron 服务，等待 `/health` 返回两个真实预热会话；启动 GPU 逐秒采样；服务加载失败或 240 秒未 ready 即失败。
5. **回放**：用隔离环境运行 `xturnix_fleurs_test.py replay`，80ms 真实时钟送音、5 秒静音尾窗、5 秒主窗口；每条新会话，影子 Listen。
6. **停服与评分**：先 `SIGTERM` 整个服务进程组并等待 30 秒，再运行 `score`；评分不加载模型、不访问服务。服务需要 `SIGKILL` 视为退出不有序，作业最终失败。
7. **汇总与清理**：核对计划分母、状态计数、评分分母和 trace 总量（≤2 GiB），记录服务峰值 RSS、GPU 显存峰值、磁盘前后变化和遗留进程；EXIT trap 始终写退出码并再次清理服务与采样进程。

## 输入参数

| 变量 | 默认值 |
| --- | --- |
| `XTURNIX_MODE` | `smoke` |
| `XTURNIX_RUN_ID` | 必填；`<root>/runs/<run_id>` |
| `XTURNIX_ROOT` | `~/interclarify-xturnix-fleurs` |
| `XTURNIX_ENV_DIR` | `$ROOT/envs/xturnix` |
| `XTURNIX_DATA_PYTHON` | `~/miniconda3/envs/interclarify-x2-turn-data/bin/python` |
| `XTURNIX_ASR_MODEL` | `~/interclarify-asr-selection/models/nemotron_en` |
| `XTURNIX_MODEL` | `$ROOT/models/xturnix-pt` |
| `XTURNIX_ASR_PORT` | `18805` |

提交脚本用 `XTURNIX_TAG` 作为 `run_id`，用 `XTURNIX_PARTITION` 选择分区（默认 `pdgpu-4090`），用 `XTURNIX_IMAGE` 指定镜像，`XTURNIX_TIMEOUT_SECONDS` 默认 14400。

集群的 `vc` 包装脚本会把提交命令中字面量 `JOB` 替换成 `$JOB`；因此经 `--cmd` 传入的变量名刻意避开该 token，使用 `XTURNIX_MODE` / `XTURNIX_RUN_ID`。旧名 `XTURNIX_JOB_MODE` / `XTURNIX_JOB_RUN_ID` 只保留给不经过调度包装的直接执行。

## 输出

```text
<root>/runs/<run_id>/
├── job/
│   ├── job.log                     # 阶段日志
│   ├── limits.json                 # 模式、上限、源码提交与开始容量
│   ├── verify_data.json            # 输入复核
│   ├── model_verification.json     # 环境/模型逐文件复核
│   ├── health.json                 # 真实 readiness
│   ├── asr_service.log             # 服务日志
│   ├── gpu.csv / gpu_samples.csv   # 设备与逐秒显存
│   ├── service_process_status.txt  # 服务 VmHWM
│   ├── replay_{dev,test}.json      # 回放报告
│   ├── score_{dev,test}.json       # 评分摘要
│   ├── job_summary.json            # 计数、指标、资源与清理结果
│   ├── exit_code.txt               # 作业退出码
│   └── post_cleanup.txt            # 停服后的残留检查
├── replay-dev/                     # 1 条 dev 协议回放与 score/
└── replay/                         # 正式或冒烟 test 回放与 score/
```

`job_summary.json` 只汇总执行事实和评分结果；作业退出 0 不表示模型质量达标。

## 提交示例

```bash
cd <frozen source worktree>
XTURNIX_TAG=xtx-005-smoke-20261023 XTURNIX_MODE=smoke \
  XTURNIX_PARTITION=pdgpu-a10 bash scripts/remote/submit_xturnix_fleurs_job.sh
XTURNIX_TAG=xtx-006-formal-20261023 XTURNIX_MODE=formal \
  XTURNIX_PARTITION=pdgpu-a10 bash scripts/remote/submit_xturnix_fleurs_job.sh
```

提交后核对 `vc list`，等待作业结束再提交下一个；同一时间只允许一个推理作业。

## 边界

单卡、8 CPU、32 GiB RAM、batch=1、单活动录音、单作业 4 小时；评分 2 个 worker；trace/结果 2 GiB、启动空闲盘 30 GiB。触限保留失败，不自动加卡或扩容，不训练、不调阈值、不接入 Layer 1/TTS/播放器。
