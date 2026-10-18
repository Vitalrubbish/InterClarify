# `scripts/remote/turnsense/`

用途说明（2026-10-18）：本文说明保留的历史/诊断实现。当前目标已确定为 Nemotron EN 160ms + Kokoro；新组合接入和训练按 [issue 任务](../../../issue/README.md) 推进，本文参数不代表新组合已部署。

## 整体作用

vendored 的 **TurnSense** 独立 ONNX HTTP 服务：一个基于**音频**的话轮检测器，对缓冲的用户语音预测 `complete` / `incomplete` / `invalid`。当前 X-Talk 组合使用它处理音频式话轮边界；组件来源和连接证据见 [xtalk_baseline_stack.md（历史快照）](https://github.com/Vitalrubbish/InterClarify/blob/c614d55/docs/xtalk_baseline_stack.md)。

`scripts/remote/run_xtalk_round1.py serve turn_detector` 在端口 8003 启动 `service.py`；X-Talk 侧的客户端是 fork 的 `models/turn_detector/turn_sense.py`，运行配置 `configs/xtalk_round1_runtime.json` 指向它。

## 来源与钉版

- 上游仓库：<https://github.com/xcc-zach/xtalk-TurnSense>
- 钉版提交：`cc0681c85771117958785faf3d6a7f402018a83e`（2026-07-06）
- 逐字 vendor：`service.py`、`infer.py`、`frontend/audio_frontend.py`、`frontend/__init__.py`、`requirements.txt`（上游 `requirements/base.txt`）。
- 未 vendor：`install.sh` / `start.sh`（我们直接起 `service.py`）、示例、图片与 TurnBench。

模型资产不在此目录，而是准备阶段放到 `$XTALK_ROUND1_MODEL_ROOT/turnsense/`：

- `model_int8.onnx`（service 默认模型），sha256 `d5105b9a…a5e4c`；
- `am.mvn`（Kaldi 风格 CMVN），sha256 `29b3c740…96ae5`。

## 文件

- [service.md](service.md)：FastAPI 服务与 CLI。
- [infer.md](infer.md)：ONNX 推理封装与音频加载。
- [frontend.md](frontend.md)：Kaldi filterbank + LFR + CMVN 前端。

## 运行环境

独立 conda 环境 `xtalk-round1-turnsense`：`numpy==2.2.6`、`librosa==0.11.0`、`soundfile==0.13.1`、`kaldi-native-fbank==1.22.3`、`fastapi==0.116.1`、`uvicorn[standard]==0.35.0`、`python-multipart==0.0.20`、`onnxruntime==1.23.2`、`PyYAML`（`check-deps` 需要）。当前该环境建在共享 home 上（未烘进 v0.3 镜像），node job 通过 `XTALK_TURNSENSE_PYTHON` 绝对路径启动；`Dockerfile.round1` 已加入该环境与 `/opt/src/xtalk-TurnSense` 副本，供后续镜像使用。
