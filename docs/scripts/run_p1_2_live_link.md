# `scripts/run_p1_2_live_link.py`

## 作用

P1.2 实时双工链路的运行入口（[engineering_implementation.md](../engineering_implementation.md) 第 5.2 节）。保持官方三服务架构（分离的 Kyutai STT/TTS + 官方 `server.py` 控制模型），可选地以子进程拉起控制模型，然后用无头双工客户端连续跑完 `configs/p1_2_scenarios.json` 中的脚本化场景，产出 P1.2 验收证据。

## 流程

1. `RunContext.create`（默认 `cluster` profile，tags `p1, live-link`）建运行目录；
2. 加载并严格校验场景；`live_link_start` 事件记录场景清单、全部场景音频的 SHA-256、服务端点、时钟与 sink 模式；
3. 探测 STT/TTS 端点（TCP），不可达即失败退出并提示先看任务单前置条件；
4. `--llm launch`（默认）：解析 P1.1 资产路径 → `verify_weight_sha256` 校验权重 → `OfficialDuplexServer` 子进程启动并就绪；`--llm connect`：连接 `--llm-url` 指向的已运行服务；
5. 构建时钟与播放所有者（`auto`：有输出设备用 sounddevice，否则 virtual），`playback_owner_ready` 事件记录实际 sink；
6. 连续执行全部场景：同一条 WebSocket 连接内场景间发 `Reset`（`--reset-mode reconnect` 则每场景新建连接）；每个场景前重置堆积峰值并把 virtual sink 的已播捕获切到 `artifacts/played_<scenario>.f32le`；
7. `evaluate_expectations` 逐场景核验 expect（`scenario_checks` 事件），写 `metrics.json`（含每场景的 `frames_sent_while_speaking`、打断取消样本数、pacing 欠 run、控制 token 序列等）；
8. `continuous_run_summary` 事件与汇总指标（双工证据计数、打断停播成功数、墙钟总时长），最后停掉子进程服务。

## 参数（要点）

- `--profile` / `--config-dir` / `--output-root` / `--run-id`；
- `--scenarios` / `--scenario`（逗号过滤）/ `--audio-root`；
- `--snapshot` / `--base-model-path` / `--source-root` / `--device` / `--dtype` / `--max-new-tokens` / `--micro-turn-seconds`；
- `--stt-ws` / `--tts-ws` / `--tts-voice` / `--llm-port`；
- `--llm launch|connect` / `--llm-url` / `--reset-mode reset|reconnect` / `--playback-sink auto|virtual|sounddevice` / `--no-verify-weight`。

## 退出码与产物

退出码 0 = 全部期望通过；2 = 有 `fail` 检查项（运行目录仍完整）。运行目录含 `manifest.json`、`resolved_config.yaml`、`environment.txt`、`events.jsonl`、`metrics.json`、`artifacts/`（官方服务日志 + 每场景已播音频 raw）。P1.3 的统一事件日志会复用同一 `events.jsonl` 格式并扩展事件字典。

## 约束

不加任何 Layer 2 逻辑；服务端代码零修改；脚本只读取决策时刻之前的输入（场景音频全部来自预生成文件）。
