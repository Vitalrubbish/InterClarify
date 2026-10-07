# `scripts/check_audio_io.py`

## 作用

P0 音频 I/O 条件探测，对应 [engineering_implementation.md](../../engineering_implementation.md) 第 4.2 节第 3 项：记录输入/输出设备、采样率、声道、缓冲区块大小与回声消除条件。

## 行为

- 目标参数来自命令行（默认 `--sample-rate 24000`、`--chunk-ms 80`），据此给出 `suggested_blocksize`；
- 通过 `sounddevice` 列出 host API、输入/输出设备、默认设备与默认采样率；
- 依据 host API 判断是否存在操作系统级 AEC（Windows WASAPI 视为可能存在），否则在 `notes` 中提示需要软件回声抑制或 push-to-interrupt；
- `sounddevice` 不可用或不含设备时优雅降级，写入 `status`（`NO_AUDIO_BACKEND` / `NO_DEVICES` / `OK`）与说明。

## 输入输出

- `--json-out PATH`：写 JSON 报告（P0 验收证据）；
- `--require-devices`：无可用设备时返回非零；headless 集群默认不传，`NO_DEVICES` 属预期。

## 约束

本脚本只做探测，不打开音频流、不启用 AEC；local profile 是否启用软件回声抑制在 P1 决定并记录。
