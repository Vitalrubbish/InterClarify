# X2Q-014 评测作业提交

无类。`scripts/remote/submit_x2_turn_complete_jobs.sh` 把一个 X2Q-014 阶段提交到 `vc` 调度器：`smoke` 是 dev 预热加 5 条 test，`formal` 是 dev 预热加全部 100 条 test。脚本只提交，不等待、不重试、不自动加卡；提交成功不等于评测通过。

## 参数

| 变量 | 含义 |
| --- | --- |
| `X2_TURN_ROOT` | 固定实验根目录 |
| `X2_TURN_SOURCE` | 冻结的 InterClarify 检出 |
| `X2_TURN_JOB_SCRIPT` | 作业脚本路径，通常为冻结源码包中的 `run_x2_turn_complete_job.sh` |
| `X2_TURN_STAGE` | `smoke` 或 `formal` |
| `X2_TURN_TAG` | 唯一标签，提交日志为 `ROOT/logs/<tag>-<stage>.log` |
| `X2_TURN_RUN_ID` | 唯一回放 run id |
| `X2_TURN_SOURCE_COMMIT` | 可选，默认取冻结源码 HEAD |
| `X2_TURN_IMAGE` | 容器镜像，默认沿用现役 xtalk-round1 镜像 |
| `X2_TURN_GPU_PARTITION` | 默认 `pdgpu-4090` |
| `X2_TURN_TIMEOUT` | 作业内超时，默认 14400 秒 |

## 提交前检查

以下任一路径已存在时脚本拒绝提交：提交日志、作业输出目录、目标 run id、`dev-<tag>`。这样上一轮失败或成功证据不会被覆盖，也不会混入正式分母。

## 资源

- 单作业 1×24 GiB GPU、8 CPU、32 GiB RAM，单作业上限 4 小时。
- 模型与冻结输入只读复用，不在作业内下载或重建。
- 服务只监听 `127.0.0.1`；GPU 推理仅走调度节点，登录节点只做提交与轮询。

## 用法

```bash
export X2_TURN_ROOT=~/interclarify-x2-turn-complete
export X2_TURN_SOURCE=$X2_TURN_ROOT/source/InterClarify-20261022-x2q014
export X2_TURN_JOB_SCRIPT=$X2_TURN_ROOT/source/x2q014/run_x2_turn_complete_job.sh
X2_TURN_STAGE=smoke X2_TURN_TAG=20261022-r2 X2_TURN_RUN_ID=smoke-20261022-r2 \
  bash "$X2_TURN_ROOT/source/x2q014/submit_x2_turn_complete_jobs.sh"
X2_TURN_STAGE=formal X2_TURN_TAG=20261022-r3 X2_TURN_RUN_ID=formal-20261022-r1 \
  bash "$X2_TURN_ROOT/source/x2q014/submit_x2_turn_complete_jobs.sh"
```

提交后用 `vc list` 查看状态，用 `vc logs <job>` 查看容器输出；最终结果以 `ROOT/runs/<run_id>/job/exit_code.txt` 和评分文件为准。冒烟只排查协议、时钟、格式与资源，不据分数调参；正式分数只来自 `formal` 阶段。
