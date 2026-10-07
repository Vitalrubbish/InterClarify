# `scripts/run_p1_offline_sample.py`

## 作用

P1.1 的离线样例入口：加载固定 DuplexCascade 权重，用脚本化 micro-turn 文本驱动官方控制模型，把输入、每轮原始输出、GPU 峰值显存与延迟写入 P0 风格的运行目录。

## 流程

1. 用 `RunContext.create`（默认 `cluster` profile）创建运行目录；
2. 解析路径：`source_root` 默认 `<repo_root>/3rd-party/DuplexCascade`；`snapshot` 与基础模型默认在 `<model_root>/modelscope/…` 下取最新版本；
3. 构建 `OfficialControlAdapter` 并 `run_script`；
4. 每轮记录 `micro_turn_generation` 事件（控制 token、文本、token id、延迟）；
5. 写 `metrics.json`：`num_turns`、`total_latency_s`、`mean_latency_s`、`rtf_vs_micro_turn`、`cuda_peak_allocated_mb`、`cuda_peak_reserved_mb` 等。

## 参数

- `--profile` / `--config-dir` / `--output-root` / `--run-id`；
- `--snapshot`、`--base-model-path`、`--source-root`：覆盖默认资产路径；
- `--script`：JSON 列表，元素为字符串或 `null`（`null` = 该 micro-turn 无新语音，即官方 `<|no voice|>`）；缺省用 `DEFAULT_SCRIPT`；
- `--device`、`--dtype`、`--max-new-tokens`、`--micro-turn-seconds`。

## 固定输入

官方 README 未提供示例话语，默认 `DEFAULT_SCRIPT` 使用一段无领域倾向的简短问候/请求（`Hello` → `how are you today` → 静默一轮 → `could you tell me a short joke`），用于观察控制 token 随前缀变化，不涉及 InterClarify 目标域。

## 约束

本脚本不做 ASR/TTS，不加 Layer 2 决策；只运行官方控制模型路径（P1.2 才接入真实音频与 TTS）。
