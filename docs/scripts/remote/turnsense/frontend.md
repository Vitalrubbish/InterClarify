# `scripts/remote/turnsense/frontend/audio_frontend.py`

## 整体作用

TurnSense 的声学前端：用 `kaldi-native-fbank` 提取 fbank，再做 LFR（低帧率）与 CMVN，产出 ONNX 输入特征。`frontend/__init__.py` 仅导出 `AudioFrontend`。

## 关键方法

- `__init__`：配置 `knf.FbankOptions`（采样率、窗、帧长/帧移、mel 维数、`dither`），并加载 CMVN 文件。
- `fbank`：把波形放大到 16-bit 量级后在线取帧，得到 `[frames, n_mels]`。
- `apply_lfr`：按 `lfr_m`/`lfr_n` 堆叠相邻帧，头部左填充。
- `apply_cmvn` / `lfr_cmvn`：按 CMVN 的均值/方差做归一化；`extract_features` 串起 fbank → LFR → CMVN。
- `load_cmvn`：解析 Kaldi 风格 `am.mvn` 的 `<AddShift>`/`<Rescale>` 段。
