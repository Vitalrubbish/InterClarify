# `scripts/run_p0_smoke.py`

## 作用

P0 确定性离线冒烟脚本，验证“同一离线输入在相同配置下产生结构一致的日志”（[engineering_implementation.md](../engineering_implementation.md) 第 4.3 节）。它不进行任何模型推理，只走通配置加载、运行目录、清单写入与分段音频事件记录。

## 流程

1. 通过 `RunContext.create` 加载 profile（默认 `replay`），生成运行目录及 `manifest.json`、`resolved_config.yaml`、`environment.txt`；
2. 获取音频输入：`--input WAV` 时用 `soundfile` 读取并重采样到目标采样率；否则用配置 `run.seed` 合成确定性正弦+噪声信号；
3. 按 `audio.chunk_ms` 切成固定大小块，每块记录一条 `audio_chunk_received`（含 `seq`、`sample_offset`、`num_samples`），并记录 `audio_input_opened` / `audio_input_closed`；
4. 写 `metrics.json`（块数、总样本、时长、RMS 等）并 `finalize`。

## 输入输出

- `--profile`、`--config-dir`、`--output-root`、`--input`、`--seed`、`--run-id`；
- 标准输出打印 `{run_id, run_dir, status}`。

## 约束

- 相同配置与相同输入产生相同的事件类型序列与相同 `metrics.json`；墙钟字段（`wall_time`、`monotonic_ms`）天然不同，因此比较“结构”而非逐字节；
- 事件格式即为 P1.3 统一事件日志的雏形，字段命名保持一致。
