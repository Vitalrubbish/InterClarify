# `scripts/prepare_p1_2_scenarios.py`

## 作用

生成 P1.2 场景语音音频。场景 JSON（`configs/p1_2_scenarios.json`，入库）中每个带 `synth_text` 的 segment 由本脚本通过**固定的 Kyutai TTS 服务**合成 24 kHz 单声道 float32 wav，写到配置的音频根目录（默认 `assets/p1_2_scenarios/`，`*.wav` 不入库）。用系统自己的 TTS 合成“用户语音”，保证脚本化用户在声学上与系统一致。静音 segment（`audio: null`）无需生成，runner 在内存中生成零样本。

## 流程

1. 读配置（`duplexcascade.tts_ws`、`duplexcascade.tts_voice`）与场景 JSON，展开工作清单（scenario / label / text / 输出路径）；`--dry-run` 只打印清单；
2. 对每个 segment：按官方 `server.py` 的 TTS 客户端协议连接（`format=PcmMessagePack`、`voice`、auth 查询参数与 `kyutai-api-key` 头，兼容 websockets 12/13+ 的 header 参数名），发送 `Text` + `Eos`，收集 `Audio` 帧直到空闲超过 `eos_timeout_s`（该端点无显式结束标记）；
3. 首尾加短静音（`--lead-silence-s` 默认 0.10s、`--tail-silence-s` 默认 0.30s，避免边界爆音并给 ASR 干净起音）；
4. 写出 wav 并打印 JSON 摘要（样本数、时长、SHA-256）——live-link runner 运行时会重新哈希并写入 `live_link_start` 事件，形成“文本 + TTS 版本 + 音频摘要”的溯源链。

## 约束

- 只处理带 `synth_text` 的 segment；带 `synth_text` 却无 `audio` 路径会报错；
- 每次运行覆盖旧文件，保证音频与入库文本始终一致；
- 需要 TTS 服务已运行；本地开发机可用 `--profile local` 指向本地 TTS。
