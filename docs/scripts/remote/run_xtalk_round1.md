# `scripts/remote/run_xtalk_round1.py`

## 整体作用

读取首轮 YAML，下载锁定模型、检查依赖并启动当前 X-Talk 链路所需的 ASR/LLM/TurnSense/TTS 服务；也提供独立 ASR/TTS smoke。此脚本不实现 InterClarify、Layer 0 或新的仲裁器。

## 核心函数

- `download_models`：首次把模型 revision 解析为具体 SHA，并在下载前写入锁定文件；后续复用已有锁定记录，ID/revision 不一致时报错。下载完成后记录真实 snapshot 路径，失败保留未完成状态。
- `asr_smoke`：读取 16 kHz 单声道 WAV，按原速输入官方 Qwen 流式 API。计时前先用静音块预热解码路径，避免一次性冷启动抬高首 partial；保存每次调用的累计文本、修订、到达时间与最终转写，并同时记录墙钟首 partial（`first_partial_seconds`）与音频相对首 partial（`first_partial_audio_seconds`），区分模型加载与流式推理时间。`--audio-dir` 可在一个模型加载内遍历目录下所有 `input.wav`（每个样本写自己的 `asr_report.json`，并汇总 `asr_smoke_summary.json`）；`--unfixed-chunk-num` / `--unfixed-token-num` / `--emit-committed-prefix` / `--no-emit-committed-prefix` 可在不改配置的情况下比较流式契约。开启定稿前缀后，每个事件与报告额外给出 `visible_text` / `visible_revisions` / `commit_stalls`，即「运行时真正会看到的文本、其改写次数与解码器回改到已交付内容的次数」（缺少 `is_final` 边界时是保守下界；真实链路的逐拍核对结论见 [阶段 A 任务单 §9.5](../../xtalk_a4_remote_acceptance.md)（核对工具已在 2026-10-14 清理中移除）。输入不再要求 16 kHz：任意单声道 WAV 会按运行时 `_load_pcm16` 的同一路径（优先 `soxr`，环境缺 `soxr` 时退化为 numpy 线性插值）重采样到 `asr_streaming.sample_rate`，报告与汇总里记录 `source_sample_rate` 与 `resampler`，便于区分"模型差异"与"重采样差异"。
- `tts_smoke`：通过现有 `MossTTSRealtime` 客户端发送分片文本并并发接收音频；保存 WAV、冷/热态延迟、实际采样率、是否在 flush 前收到音频。失败不输出 PASS。`--text` 可重复以显式给出多个分片，并用 `--gap-seconds` 控制片间间隔；`--stream-chunk-words N` 会把每个 `--text` 再按 N 个词切分成小片、逐片推送，用来模拟 LLM token 流式输入（默认 0 关闭）。报告额外记录 `text_chunk_count` 与 `stream_chunk_words`。
- `check_dependencies`：按 `dependency_candidates` 校验当前环境实际安装的 torch / transformers / vLLM（TTS 角色还含 flash-attn；turn detector 角色校验 onnxruntime 与 kaldi-native-fbank）版本与可导入性，返回 `ok`、逐包 `version_ok`/`importable`；用于在启动时把镜像版本漂移暴露成明确失败。
- `serve` / `select_gpu`：从作业分配的可见设备中选择逻辑卡，读取锁定 snapshot，启动 ASR、LLM、TurnSense 或 MOSS 服务。`serve asr` 在 ASR 环境内启动本地 Qwen3-ASR 流式 HTTP 服务（[qwen3_asr_service.md](qwen3_asr_service.md)，端口 8005）。`serve turn_detector` 启动 vendored 的 TurnSense ONNX 服务（[turnsense/README.md](turnsense/README.md)，端口 8003）：它按 `services.turn_detector.onnx_file`/`cmvn_file`（相对 model root）定位资产，默认以配置的 `xtalk-round1-turnsense` 环境运行；若设置了环境变量 `XTALK_TURNSENSE_PYTHON` 则改用该解释器直接启动。`serve llm` 仍走 `vllm serve`，`serve tts` 启动 MOSS 服务。`serve tts` 还会把配置里的 `services.tts.local_attn` / `local_compile`（吞吐补丁的部署默认值，2026-10-15 定为 `sdpa` + `inductor`）转成 `XTALK_TTS_LOCAL_ATTN` / `XTALK_TTS_LOCAL_COMPILE` 传给服务；环境里已显式设置同名变量时以环境为准（吞吐 A/B 逐臂扫一个杠杆正是这样做的）。`--port` 可覆盖配置里的端口（同一节点上需要串行重启同类服务、或并行跑多份实例时用，见 [run_tts_throughput_ab_node_job.md](run_tts_throughput_ab_node_job.md)）。
- `main`：解析 `download`、`asr-smoke`、`tts-smoke`、`check-deps`、`serve` 子命令及显式目录。脚本没有自定义类。

下载只需要准备环境；ASR smoke 在 Qwen conda 环境运行，TTS smoke 在安装 X-Talk 的客户端环境运行。每份 smoke 产物复制输入配置与模型锁定文件。锁定文件、音频和结果保存在仓库外或被忽略的产物目录，重跑 smoke 必须选择新的目录。
