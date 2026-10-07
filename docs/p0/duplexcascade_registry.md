# DuplexCascade 参考底座登记（P0）

对应 [engineering_implementation.md](../../engineering_implementation.md) 第 4.2 节第 2 项：登记官方仓库提交、模型权重修订、许可证与 Hugging Face 访问条件。本文件只做登记与可行性判断，P0 不下载权重、不运行模型；实际复现见 P1。

## 代码仓库

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/sbintuitions/DuplexCascade |
| 固定提交 | `42893024ca90c8de8ac3ed624467ebc123512ff8`（main） |
| 提交时间 | 2026-03-24T07:56:40Z |
| 许可证 | MIT |
| 入口 | `server.py`（LLM 端，默认端口 `31606`）、`model.py`、`requirements.txt` |
| 论文 | arXiv 2603.09180 |

架构要点：级联 ASR–LLM–TTS + micro-turn；LLM 用控制 token 决定等待/回答/backchannel，不依赖外部 VAD。官方 README 要求 Python 3.10。

### 控制 token（来自 `server.py`）

```text
<|no voice|>              用户本 micro-turn 无新增语音
<|user is talking|>       用户正在说
<|user finish talking|>   用户说完，可开始回答
<|user is thinking|>      用户停顿思考
<|user interruption|>     用户插话，需停播
<|user backchannel|>      倾听反馈
```

micro-turn 窗口默认 `overlap_window_s=0.6`，`max_new_tokens=64`。这些值同时固定在 `configs/base.yaml` 的 `clock.micro_turn_seconds` 与 `duplexcascade.max_new_tokens`。

### 服务分工与端点

| 组件 | 实现 | 端点 |
| --- | --- | --- |
| ASR | Kyutai `delayed-streams-modeling`（`moshi-server`，Rust） | `ws://127.0.0.1:31607/api/asr-streaming` |
| TTS | Kyutai `delayed-streams-modeling` | `ws://127.0.0.1:31608/api/tts_streaming` |
| LLM | Qwen2-7B-Instruct + LoRA，`server.py` | `0.0.0.0:31606` |
| 浏览器前端 | `web/` 静态页 | 同 `31606` |

LLM 端通过 `msgpack` 与 ASR/TTS 通信，音频为 24 kHz 单声道 float32；ASR 每 1920 samples（80 ms）发送一次，与 `configs/base.yaml` 的 `audio.chunk_ms=80` 一致。

## 模型权重

| 项 | 值 |
| --- | --- |
| HF 仓库 | `sbintuitions/DuplexCascade` |
| 固定修订 | `31c038ece2f006a28722dd60d1df3868fbb2cc42` |
| 访问条件 | 公开仓库，`gated=auto`：需登录 HF 并接受页面条件后自动放行 |
| 主要文件 | `model_state.safetensors`（约 17.4 GB）、`tokenizer/`、`train_cfg.json`、`LICENSE` |
| 基线 LLM | `train_cfg.json` 指定，默认 `Qwen/Qwen2-7B-Instruct`；`server.py --hf-repo-id` 可覆盖 |

## 网络与镜像（集群现状，2026-10-07 探测）

| 目标 | 结果 |
| --- | --- |
| `https://huggingface.co` | 不可达（连接超时） |
| `https://hf-mirror.com` | 可达（HTTP 200），可读取仓库元数据 |
| `https://github.com` 网页 / raw | 可达 |
| `https://pypi.tuna.tsinghua.edu.cn/simple` | 可达 |
| `https://conda.anaconda.org/conda-forge` | 不可达；`mirrors.tuna.tsinghua.edu.cn` conda-forge 可达 |
| `https://download.pytorch.org/whl/cu121` | 可达 |

因此集群统一使用 `HF_ENDPOINT=https://hf-mirror.com`（已写入 `configs/cluster.yaml` 的 `env` 段与作业脚本）。

## 访问风险与替代时间表

1. **gated 权重**：`hf-mirror` 可读元数据，但 `model_state.safetensors` 下载可能需要 HF token 接受条件。P0/P1 开始前需确认已登录并接受条件；若暂时不可得，先完成接口、日志与回放桩（P1.3），取得访问后优先补齐。
2. **ASR/TTS 语言与实时性**：官方 Kyutai STT/TTS 面向英语/法语，目标域“日程时间选择”可能需要中文。若确不适配，允许替换 ASR/TTS，但必须先保存官方组合结果，替换后的底座由所有后续策略共用，不得为单个对照单独调整（[engineering_implementation.md](../../engineering_implementation.md) 第 5.1 节）。
3. **权重体积**：单文件约 17.4 GB，需确认共享存储空间（当前 `hpc_stor03` 剩余约 730 GB）。

## 相关公开评测

- Full-Duplex-Bench：https://github.com/DanielLin94144/Full-Duplex-Bench（P1.4 接入，本机已有只读副本 `~/Full-Duplex-Bench`）。

以上提交号、HF 修订与访问条件在 P1 开始时再次核对；模型与数据集不进 Git，只登记来源与校验值。
