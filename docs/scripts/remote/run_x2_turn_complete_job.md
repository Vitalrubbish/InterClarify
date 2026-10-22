# X2-Turn 单卡部署作业

无类。`scripts/remote/run_x2_turn_complete_job.sh` 在调度分配的单卡上启动冻结版本 X2-Turn 服务，证明状态头与有效延迟真的生效，并用 dev 输入做一次协议诊断。当前只实现 `deploy` 阶段；正式 100 条回放与评分由后续工作单在同一根目录扩展，本脚本不产生指标、不启动回答 LLM/TTS，也不使用演示能量门或 `FrameTurnController`。

## 前置

- 已由安装阶段完成环境锁 `ROOT/env/x2_turn_vllm_environment.json`。
- 已由模型阶段完成 `ROOT/env/x2_turn_model_lock.json` 与 `ROOT/models/X2-Turn-4B-0812-vllm`。
- 工作盘空闲不少于 100 GiB；推理只允许一张 24 GiB GPU、8 CPU、32 GiB、单作业 4 小时。

## 流程

1. 校验 conda 环境、导出权重、两份锁文件与磁盘空间，写 `manifest.json`。
2. 保存 GPU 型号/驱动/显存，并按秒采样显存与利用率。
3. `setsid` 启动 `vllm serve`：`--tokenizer-mode mistral --enforce-eager --gpu-memory-utilization 0.85 --max-model-len 8192`，只监听 `127.0.0.1:18011`。上下文长度必须受限：vLLM 的 encoder cache 画像预算等于 `max_model_len`，默认 131072 会在 24 GiB 卡上与 9.1 GiB 权重叠加后没有 KV 空间（实测报 `No available memory for the cache blocks`）；8192 个音频 token 约合 11 分钟音频，足够单轮诊断与后续 FLEURS 输入。
4. 轮询 `/health` 直到就绪（默认上限 1200 秒），同时确认进程未退出。
5. 要求服务日志出现 `Loaded Voxtral MTP vad_lm_head`，证明状态头已加载而不是回退到 ASR 头。
6. 读 `tekken.json` 与 `config.json` 推导延迟，并用 `mistral-common` 的 `get_num_delay_tokens()` 交叉核对；要求 6 个 delay token、480 ms，且 ID38 映射为 `turn_end`，结果写 `effective_config.json`。
7. 用 dev 输入运行 `x2_turn_service_probe.py`，要求非空转写和至少一帧原生状态；可选 `X2_TURN_SMOKE_AUDIO` 再跑一条冒烟输入。
8. EXIT trap 关闭进程组，保存 `/proc/<pid>/status`、退出码并停止采样。

## 参数

| 变量 | 含义 |
| --- | --- |
| `X2_TURN_ROOT` / `X2_TURN_OUTPUT` | 实验根目录与本次输出目录（必须不存在） |
| `X2_TURN_STAGE` | 目前仅 `deploy` |
| `X2_TURN_SOURCE` | 冻结的 InterClarify 源码检出，用于调用诊断客户端 |
| `X2_TURN_SOURCE_COMMIT` | 记录到 manifest 的源码提交 |
| `X2_TURN_CONDA_ENV` | conda 环境前缀 |
| `X2_TURN_MODEL` | 导出权重目录 |
| `X2_TURN_PORT` / `X2_TURN_READY_TIMEOUT` / `X2_TURN_DRAIN_SECONDS` | 服务端口、就绪上限、观察窗 |
| `X2_TURN_MAX_MODEL_LEN` / `X2_TURN_GPU_MEMORY_UTILIZATION` | 上下文上限（默认 8192）与显存占比（默认 0.85） |
| `X2_TURN_DEV_AUDIO` | dev WAV 目录（默认固定 FLEURS dev 音频目录） |
| `X2_TURN_SMOKE_AUDIO` | 可选冒烟音频 |

## 输出

`X2_TURN_OUTPUT` 下保存 `manifest.json`、`gpu.csv`、`gpu_samples.csv`、`service.log`、`readiness.json`、`effective_config.json`、`probe_dev/`、可选的 `probe_smoke/`、`service_process_status.txt` 与 `exit_code.txt`。

服务启动或预热成功不等于正式测试完成；本作业的结论只是"冻结服务能输出 ASR 与原生状态，且 delay 配置有效"。
