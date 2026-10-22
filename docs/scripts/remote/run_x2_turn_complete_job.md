# X2Q-014 单阶段评测作业

`scripts/remote/run_x2_turn_complete_job.sh` 在一个调度 GPU 作业内完成 X2Q-014 的一个评测阶段：启动冻结的 X2-Turn vLLM 服务，复核有效 delay 和状态映射，用冻结 dev 输入预热，再运行固定的 5 条冒烟或 100 条正式输入，随后对同一批原始 trace 分别运行 ASR 与 complete 评分并停止服务。脚本不启动回答 LLM、TTS、上游控制器或任何 FDB 组件。

## 阶段与输入

| 变量 | 含义 |
| --- | --- |
| `X2_TURN_ROOT` | 固定实验根目录，含数据、模型、锁与 `runs` |
| `X2_TURN_SOURCE` | 冻结的 InterClarify 检出，提供回放与评分客户端 |
| `X2_TURN_STAGE` | `smoke` 或 `formal` |
| `X2_TURN_TAG` | 唯一标签，决定作业输出与 dev run id |
| `X2_TURN_RUN_ID` | 唯一正式回放 run id，输出写 `ROOT/runs/<id>` |
| `X2_TURN_DEV_RUN_ID` | 可选，默认 `dev-<tag>` |
| `X2_TURN_OUTPUT` | 可选，作业证据目录；默认 `ROOT/runs/job-<tag>-<stage>` |
| `X2_TURN_CONDA_ENV` | vLLM 服务环境，默认 `interclarify-x2-turn-vllm` |
| `X2_TURN_REPLAY_ENV` | 回放与评分环境，默认 `interclarify-x2-turn-data` |
| `X2_TURN_GPU_PARTITION` | 由提交脚本使用，默认 `pdgpu-4090` |

输出目录已存在时脚本立即失败，不覆盖上一轮证据。`smoke` 固定前 5 条 test；`formal` 固定全部 100 条 test；两者都先跑 1 条 dev，预热不计入正式分母。

## 执行流程

1. 检查两个 conda 解释器、导出权重、环境/模型锁、冻结 manifest 与回放客户端；回放环境必须能导入 `soundfile`、`websockets` 与固定 normalizer。
2. 记录空闲磁盘、源码/客户端/作业脚本 SHA256、模型 revision、数据 manifest SHA256、`pip freeze`，并生成作业 `manifest.json`。
3. 启动 GPU 采样与进程内存采样，再用 `setsid` 启动 vLLM；只监听 `127.0.0.1:18011`。
4. 等待 `/health`，要求日志出现状态头加载；从模型 `tekken.json`、`config.json` 与 vLLM tokenizer 复核 6 个 delay token / 480 ms，并核对 ID38 为 `turn_end`。
5. 依次运行 dev 预热、目标阶段回放、ASR 评分与 complete 评分；每个子命令的退出码单独保存。
6. 校验计划数、评分行数、正式样本标记，以及目标轮与 dev 预热是否存在失败 trace；任一失败或评分文件缺失都使作业退出码非 0。通过后把作业证据复制到 `ROOT/runs/<run_id>/job/`。
7. 退出时停止服务、GPU 与内存采样器，并写 `exit_code.txt`。失败样本或评分失败不阻止原始 trace 保留。

## 产物

`ROOT/runs/<run_id>/` 保存 `run.json`、冻结 manifest 副本、逐例原始 trace、`asr_scores.json`、`complete_scores.json` 与 `job/`。`job/` 内有服务日志、`effective_config.json`、`readiness.json`、GPU/内存采样、各阶段退出码与 `validation.json`。

回放逐例失败仍写入评分分母；complete 的 `null` 与非命中不被改写成 0 ms。作业退出码为 1 时仍保留已有证据，是否重跑由人工判断，不自动加卡或无限重试。

## 资源与边界

服务作业最多 1×24 GiB GPU、8 CPU、32 GiB RAM，单作业上限 4 小时；启动前要求工作盘至少 100 GiB 空闲。本脚本不下载模型或数据，不修改冻结输入，不启动对话 LLM/TTS/Judger，也不在登录节点加载 GPU 模型。
