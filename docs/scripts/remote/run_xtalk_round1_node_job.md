# `scripts/remote/run_xtalk_round1_node_job.sh`

## 整体作用

首轮 X-Talk 模型服务验收的集群节点作业，在分配的容器内执行并把所有证据写入共享存储 `$XTALK_ROUND1_ARTIFACT_ROOT/<mode>/<tag>/`。按任务单要求，GPU 推理只在该作业内执行。单步失败不中断整份作业，每步状态追加到 `steps.jsonl`，结束后以失败数作为退出码。

## 模式与步骤

- `asr`（1 卡作业）：以 `--gpu-index 0` 依次运行 0.6 / 1.2 / 2.0 秒解码窗口的 ASR smoke，输出 `asr-06` / `asr-12` / `asr-20`。
- `chain`（4 卡作业）：启动三服务后，在同一节点跑完整路径——ASR（逻辑卡 2）转写输入 WAV → 用 LLM 服务做流式对话并测首 token 延迟 → 用 MOSS TTS 合成回复并测首音频。TTS 跑两次：一次把整段回复一次性喂入（`chain-tts`），一次用 `--stream-chunk-words 6 --gap-seconds 0.12` 把同一回复按词分片流式喂入（`chain-tts-stream`，模拟 token 流式、更接近真实对话首音频）。各阶段结果聚合为 `chain_report.json`（含 `content_ok` 与 `tts`/`tts_stream` 两组读数），并把整个 run 目录复制到 `$INTERCLARIFY_ROOT/data/runs/<tag>/`。该链路是顺序分阶段测量（ASR final → LLM 首 token → TTS 首音频），并非并发全双工。
- `services`（4 卡作业）：
  1. 采集 `nvidia-smi`、仓库提交与模型锁定文件；后台每 10 秒采样一次 GPU 显存与利用率（`gpu_samples.csv`）用于峰值追溯。
  2. 校验 `base` 与四个 `xtalk-round1-*` 环境在容器内可导入（提前暴露 glibc/二进制兼容问题），失败即中止。
  3. 用 `setsid` 先后启动 LLM、XTurnix、MOSS TTS（逻辑卡 0/1/3），`wait_http` 轮询 `/v1/models`、`/health`，各给 30 分钟加载预算。
  4. 按任务单第 5 节执行 curl 检查（含流式 chat completion），确认轮次模型服务名为 `xturnix`；用客户端环境的 `XTurnix` 适配器对运行中的服务实测 listening/speaking 两组决策，校验动作落在 keep/start 与 keep/stop 合法集合内；在客户端环境运行 `tests/test_moss_tts_realtime.py` 与完整 pytest，结果分别落盘，不把未运行项当通过。
  5. 对运行中的 TTS 服务依次执行 `tts-cold`、`tts-warm`、`tts-gap2`（双流观察）三组 smoke。
  6. 按进程组与命令行模式双重清理服务进程，停止 GPU 采样。

`step_status` 以 JSONL 记录每步 PASS/FAIL；服务日志在 `service_logs/`，curl 与 pytest 结果分别在 `curl/`、`pytest/`。
