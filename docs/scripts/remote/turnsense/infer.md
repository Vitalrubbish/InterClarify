# `scripts/remote/turnsense/infer.py`

## 整体作用

封装 TurnSense 的 ONNX 推理：把音频（文件 / WAV 字节 / 裸 PCM / 内存数组）经前端特征化后送入 ONNX 会话，输出三分类概率与离散预测。

## 关键内容

- 常量：`LABELS = ["complete", "incomplete", "invalid"]`、`SAMPLING_RATE=16000`、`DEFAULT_AUDIO_SECONDS=MAX_AUDIO_SECONDS=8`、`DEFAULT_CLIP_MODE="tail"`、`DEFAULT_FRONTEND_CONF`（80 维 fbank、25/10 ms 帧、`lfr_m=7`/`lfr_n=6`）。
- 音频加载：`load_audio`（文件，`librosa` 失败回退 `soundfile`）、`load_audio_bytes`（先按 WAV，失败回退裸 PCM）、`load_pcm_bytes`（按 `pcm_format` 解 `s16le`/`s16be`/`s32le`/`f32le`/`u8`，含多声道下混与重采样）；统一用 `truncate_audio` 按 `clip_mode` 截到 8 秒。
- `build_session`：创建 `ort.InferenceSession`，默认 `CPUExecutionProvider`；`use_cuda` 且 provider 可用时用 `CUDAExecutionProvider`，并可通过 `TURNSENSE_INTRA_OP_NUM_THREADS`/`TURNSENSE_INTER_OP_NUM_THREADS` 控制线程数。
- `AudioClassifierInfer`：`_extract_features` 调用前端得到 `feats`/`feat_lengths`，`_run_model` 校验 ONNX 输入名后推理；`predict_file`/`predict_audio`/`predict_bytes`/`predict_pcm_bytes` 统一返回 `prediction_id`、`prediction` 与 `probabilities`。
- `process_predictions`：输出已是概率时直接使用，否则对 logits 做 softmax。
