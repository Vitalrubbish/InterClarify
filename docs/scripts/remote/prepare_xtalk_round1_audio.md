# `scripts/remote/prepare_xtalk_round1_audio.sh`

## 整体作用

把项目 `assets/p1_2_scenarios` 的 24 kHz float32 录音转换成 16 kHz 单声道 PCM16 WAV，放入 `$XTALK_ROUND1_ROOT/audio/`，供首轮 ASR 与 TTS 验收使用，并写出带来源、时长与校验值的清单。

## 核心步骤

- `convert`：调用 ffmpeg 重采样为 16 kHz 单声道 PCM16；`-nostdin` 防止 ffmpeg 消费 `find | sort` 管道（while-read 循环的经典陷阱）。
- 选段：`request.wav` 取 `barge_in_stop/01_question.wav`（自然中文问句，ASR smoke 输入）；`reference.wav` 取 `backchannel_long_speech/01_long_speech.wav`（最长干净片段，TTS 参考音色）；其余场景片段全部转换到 `audio/scenarios/`。
- 清单：`manifest.json` 记录每个文件的来源路径、采样率、时长、SHA-256 与转写状态；人工转写标注为 `pending_manual_annotation`，ASR 输出只能作为机器参考。

场景音频仅覆盖项目已有素材；日期/时间、人名、改口、中英混说等专项素材需要后续补充并人工标注。
