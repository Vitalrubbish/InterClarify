# `scripts/remote/run_xtalk_round1.py`

## 整体作用

读取首轮 YAML，下载锁定模型，并在远端执行独立 ASR/TTS smoke。此脚本只负责模型准备与证据，不实现 InterClarify、Layer 0 或新的仲裁器。

## 核心函数

- `download_models`：首次把模型 revision 解析为具体 SHA，并在下载前写入锁定文件；后续复用已有锁定记录，ID/revision 不一致时报错。下载完成后记录真实 snapshot 路径，失败保留未完成状态。
- `asr_smoke`：读取 16 kHz 单声道 WAV，按原速输入官方 Qwen 流式 API，保存每次调用的累计文本、修订、到达时间与最终转写，区分模型加载与流式推理时间。
- `tts_smoke`：通过现有 `MossTTSRealtime` 客户端发送分片文本并并发接收音频；保存 WAV、冷/热态延迟、实际采样率、是否在 flush 前收到音频。失败不输出 PASS。
- `serve` / `select_gpu`：从作业分配的可见设备中选择逻辑卡，读取锁定 snapshot，启动 LLM、XTurnix 或 MOSS 服务。
- `main`：解析 `download`、`asr-smoke`、`tts-smoke`、`serve` 子命令及显式目录。脚本没有自定义类。

下载只需要准备环境；ASR smoke 在 Qwen conda 环境运行，TTS smoke 在安装 X-Talk 的客户端环境运行。每份 smoke 产物复制输入配置与模型锁定文件。锁定文件、音频和结果保存在仓库外或被忽略的产物目录，重跑 smoke 必须选择新的目录。
