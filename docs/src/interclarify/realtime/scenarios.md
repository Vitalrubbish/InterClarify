# `src/interclarify/realtime/scenarios.py`

## 作用

P1.2 的脚本化“用户替身”：一段带调度信息的音频 segment 列表 + 声明式期望（expect），由 runner 对照记录的事件流核验。场景文件 `configs/p1_2_scenarios.json` 入库；语音音频由 `scripts/prepare_p1_2_scenarios.py` 通过固定的 Kyutai TTS 合成到 `assets/p1_2_scenarios/`（`*.wav` 不入库），静音 segment（`audio: null`）在运行时用内存零样本，无需文件。

## 数据结构

- `Segment`：`label`（如 `question` / `barge_in` / `tail_silence`）；`audio`（相对音频根目录的 wav 路径，loader 解析为绝对路径，`None` 表示数字静音）；`start_seconds`（相对场景开始的最早发送时刻——segment 顺序发送，过去的时间点自然表示“上一段发完后立刻开始”）；`duration_seconds`（截断/补零，保证调度契约）；`start_condition`（当前只支持 `tts_played_min_seconds`，等播放所有者播够时长再发，用于把插话稳定地落在回答中途，避免模型延迟差异）；`synth_text`（合成该段语音的文本，prep 脚本的输入与溯源）。
- `Scenario`：`name`（唯一）、`description`、`segments`、`expect`。

### 期望键（`expect`）

`answer_expected`、`backchannel_expected`、`barge_in_stop_expected`、`expect_no_asr`、`user_asr_contains`、`assistant_contains`、`min_tts_played_seconds`。未知键或类型错误在加载时报错（防止拼写漂移）。

## 主要函数

- `load_scenarios(path, audio_root)`：严格校验结构、键名、调度数值，并检查所有引用音频存在；缺失文件时抛出带完整清单的 `FileNotFoundError`（提示先运行 prep 脚本）。
- `load_audio_mono(path, sample_rate)`：读出单声道 float32，采样率不一致时用 `scipy.signal.resample_poly` 多相重采样。
- `materialize_segment(segment, sample_rate)`：返回该 segment 应发送的精确样本（时长截断/零填充）。
- `audio_digest(path)` / `scenario_audio_digests(scenarios)`：SHA-256 溯源；runner 在 `live_link_start` 事件里记录全部音频摘要。

## 关键约束

- loader 严格失败优先：宁可拒绝运行，不用残缺资产产出难以解释的结果；
- 音频文件按“文本 + TTS 服务 + voice”确定性派生，运行 manifest 记录音频摘要，保证可追溯。
