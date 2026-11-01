# x2_streaming_probe 配置

对应 `configs/x2_streaming_probe.json`，冻结 NTF-011 的权重来源、帧合同和门槛。

## 字段

| 字段 | 说明 |
| --- | --- |
| `model.revision` | X2Streaming-ASR 权重 revision；只记录，不用于在线拉取 |
| `model.sha256` | `model.safetensors` 的 SHA256，运行入口必须核对 |
| `model.weight_bytes` | 权重字节数，便于审计 |
| `model.relative_path` | 相对 `$HOME` 的权重位置，运行入口可用 `SOULX_X2_MODEL` 覆盖 |
| `contract.frame_ms` / `frame_samples` | 80ms、1280 样本 |
| `contract.delay_tokens` | 6 帧模型算法延迟 |
| `contract.first_user_samples` | 首块用户音频 9000 样本 |
| `contract.first_user_mel_frames` | 首块用户音频预填 56 个 mel 帧 |
| `contract.left_pad_mel_frames` | 处理器左侧 streaming pad 256 帧 |
| `contract.first_total_mel_frames` | 首块实际张量 312 帧，必须完整送入 |
| `contract.chunk_samples` / `chunk_mel_frames` | 后续每块 1680 样本、8 帧 |
| `contract.first_input_tokens` | 首块输入 token 39 个 |
| `contract.flush_frames` | EOF 后补 8 个 80ms 静音帧用于收尾 |
| `continuous_seconds` | 连续流长度 60s |
| `gpu_memory_fraction` | 单进程显存软上限比例 0.55 |
| `gate.*` | `x2_rtf ≤ 0.6`、`backlog P95 ≤ 320ms`、60s 漂移 ≤ 160ms、峰值显存 ≤ 12288MiB |
| `limits.*` | 单作业资源与时限 |

配置只冻结探针合同，不改变模型、处理器或 SoulX。权重 SHA256 不符时入口直接失败；帧合同不符时探针在合成音自检阶段失败，不进入真实音频。
