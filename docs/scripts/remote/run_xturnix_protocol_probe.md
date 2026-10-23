# XTurnix 协议预热作业入口

`scripts/remote/run_xturnix_protocol_probe.sh` 在单个调度 GPU 作业内启动冻结的 Nemotron 服务，完成真实语音预热后运行 XTurnix 协议探针，并保留服务与资源证据。它只服务 XTX-002 的 dev 验证，不是 100 条正式回放入口。

## 流程

1. 检查输出目录不存在，配置、两个 conda 环境、ASR 模型、dev 音频和 XTurnix 模型齐全。
2. 复制配置、源码提交、工作树状态、关键脚本摘要、环境锁和模型锁到输出目录。
3. 启动 `nemotron_asr_service.py`，使用 dev 音频完成两次真实预热；等待 `/health` 成功，保存健康响应。
4. 在 XTurnix 环境中运行协议探针；探针按真实时钟发送 80ms 包，执行暂停、5 秒尾窗、EOF、清理和 XTurnix 校验。
5. 退出时保存 ASR 服务 `/proc/<pid>/status`，终止整个进程组，记录 GPU 采样和退出码。

任何一步失败都以非零退出；服务日志和已生成证据保留，不能把“提交成功”当作协议通过。

## 环境变量

| 变量 | 默认值 |
| --- | --- |
| `XTURNIX_ROOT` | `~/interclarify-xturnix-fleurs` |
| `XTURNIX_PROBE_OUTPUT` | 必填，新的运行目录 |
| `XTURNIX_CONFIG` | 当前源码树的 `configs/xturnix_fleurs_test.json` |
| `XTURNIX_ENV` | `$XTURNIX_ROOT/envs/xturnix` |
| `XTURNIX_ASR_ENV` | `~/interclarify-english-integration-20261018-v1/envs/asr` |
| `XTURNIX_ASR_MODEL` | `~/interclarify-asr-selection/models/nemotron_en` |
| `XTURNIX_DEV_AUDIO` | 冻结 dev WAV |
| `XTURNIX_PROBE_TIMEOUT` | 1800 秒，仅限制探针本体 |

## 输出

```text
<output>/
├── config.json                  # 冻结配置副本
├── source_commit.txt
├── source_status.txt
├── source.sha256
├── health.json
├── gpu.csv
├── gpu_samples.csv
├── service.log
├── service_process_status.txt
├── probe.json
├── probe/
│   ├── probe.json
│   ├── asr_evidence.json
│   └── xturnix_evidence.json
├── probe.log
└── exit_code.txt
```

## 资源与边界

作业提交上限为 1 张 GPU、8 CPU、32 GiB RAM、batch=1、单活动录音；探针顺序执行，不并发请求。脚本不下载模型、不安装依赖、不训练、不调阈值、不启动 TTS 或播放器，也不把 start 动作实际执行。模型只在调度节点运行，不登录节点启动 GPU 推理。

作业结束后必须核对 `exit_code.txt`、`probe/probe.json` 的 `passed`、`probe/probe` 内的检查项和 GPU/RSS 峰值，再决定是否进入 XTX-003。
