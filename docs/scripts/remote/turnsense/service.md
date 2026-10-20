# `scripts/remote/turnsense/service.py`

## 整体作用

TurnSense 的 FastAPI HTTP 服务。启动时加载 ONNX 与会话，暴露推理端点；供 X-Talk 的 `TurnSense` 客户端在 `speech_pause` 时调用 `/infer/bytes`。

## 接口

- `GET /healthz`：返回 `status`、`model_loaded` 与三类标签；node job 用它做就绪检查。
- `POST /infer/file`：上传音频文件（WAV 等）。
- `POST /infer/json`：`{"audio_base64": ..., "source": ...}`。
- `POST /infer/bytes`：裸字节；若带 `X-Audio-Format`/`Content-Type: audio/pcm` 等则按 PCM 解析（`X-Audio-Sample-Rate`/`X-Audio-Channels`），否则按 WAV 解析。返回 `prediction`（`complete`/`incomplete`/`invalid`）与 `probabilities`。

## 关键参数与结构

- `InferenceService`：持有 `AudioClassifierInfer`（见 [infer.md](infer.md)）、并发信号量与线程池；把阻塞推理放到 `run_in_executor`，端点保持异步。
- `ensure_default_model_assets`：未显式给 `--onnx-path` 时，按默认路径下载 ONNX 与 CMVN（本仓库由准备阶段预置，不走下载）。
- `build_app`：`lifespan` 在启动时校验模型文件存在并构建服务；缺文件直接失败。
- CLI：`--host/--port`、`--onnx-path`/`--cmvn-file`、`--max-concurrency`/`--max-workers`、`--audio-seconds`、`--clip-mode`（`head`/`tail`，默认 `tail`，即超长音频取尾部）、`--use-cuda`（`onnxruntime-gpu` 可用时启用 CUDA provider）。

## 与首轮集成

`run_xtalk_round1.py serve turn_detector` 以 `--onnx-path`/`--cmvn-file` 指向 `$XTALK_ROUND1_MODEL_ROOT/turnsense/` 内的资产，`--clip-mode tail` 与 `use_cuda` 取自配置。
