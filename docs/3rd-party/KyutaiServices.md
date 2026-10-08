# Kyutai STT/TTS 服务登记（P1.2 部署）

对应 [engineering_implementation.md](../engineering_implementation.md) 第 5.2 节 P1.2：官方 DuplexCascade 的 ASR/TTS 后端是 Kyutai `delayed-streams-modeling` 的 Rust `moshi-server`。本文登记部署所用的来源、版本、许可证与集群适配；构建与运行脚本在共享存储 `interclarify-kyutai/`，登记入库的是本文档与仓库内 `scripts/remote/` 的启动/作业脚本。

## 组件与固定版本

| 组件 | 来源 | 固定版本 | 许可证 |
| --- | --- | --- | --- |
| 服务配置 | https://github.com/kyutai-labs/delayed-streams-modeling | 提交 `4c4f65e1`（main，2026-01-26） | MIT（Python 部分）/ Apache-2.0（Rust 后端） |
| 服务源码（crate） | https://github.com/kyutai-labs/moshi 的 `rust/moshi-server` | crates.io `moshi-server@0.6.4`（unmute start_tts.sh 固定；源码提交 `9837ca32`） | Apache-2.0 |
| TTS Python 组件 | `moshi` PyPI 包（uv.lock 固定） | `0.2.8`（Python 3.12.8 venv） | MIT |
| STT 权重 | `kyutai/stt-1b-en_fr-candle` | 快照 + SHA-256 清单（`interclarify-p0-models/kyutai/stt-1b-en_fr-candle/sha256_manifest.json`） | CC-BY 4.0 |
| TTS 权重 | `kyutai/tts-1.6b-en_fr` | 快照 + SHA-256 清单 | 以 HF 仓库声明为准（部署时核对） |
| 音色 | `kyutai/tts-voices` | 快照 + SHA-256 清单 | 以 HF 仓库声明为准 |

服务协议：LLM 服务端通过 msgpack over WebSocket 访问 `moshi-server`（STT `/api/asr-streaming` 入站 Audio 帧、出站 Word；TTS `/api/tts_streaming` 入站 Text/Eos、出站 Audio 帧），与 `3rd-party/DuplexCascade/server.py` 的客户端代码一致。

## 集群构建（一次性，已完成于调试 GPU 节点）

构建脚本：`interclarify-kyutai/build_moshi_server.sh`，复刻 unmute `dockerless/start_tts.sh` 的步骤：

1. `uv sync --frozen` 按 `moshi/rust/moshi-server/uv.lock` 建 Python 3.12.8 venv（moshi 0.2.8、torch 2.6.0+cu124；PyPI 走清华镜像；uv.lock 仅元数据经 uv 0.7.13 刷新，**版本零漂移**）；
2. `cargo install --locked --features cuda moshi-server@0.6.4`：nvcc 用 conda-forge CUDA 12.6（节点自带 12.2 头文件与 candle-kernels 0.9.1 不兼容），`CUDA_COMPUTE_CAP=89`（candle 的 bf16 kernel 被 `__CUDA_ARCH__ >= 800` 门控，PTX 必须按 4090 队列的 sm_89 生成，运行时由驱动 JIT 为 SASS）；`PYO3_PYTHON`/`LD_LIBRARY_PATH` 指向 venv；链接库取 venv 内 nvidia wheels（cu124，与嵌入 Python/torch 同套，避免双 libcudart）。产物 `bin/bin/moshi-server`（SHA-256 见 `bin/moshi-server.sha256`）。

网络事实（2026-10-08，调试节点）：github 网页/raw、crates.io 网站、rsproxy、ghproxy 镜像不可达；`api.github.com`、`codeload.github.com`、`static.crates.io`、`index.crates.io`、`static.rust-lang.org`、`hf-mirror.com`、清华 PyPI/conda-forge 镜像可达；GitHub ssh（`git@github.com`）可用。源码经 codeload tarball 获取；python-build-standalone 经 GitHub API 资产端点慢速下载。

已知限制：调试节点为 RTX 2080 Ti（sm_75），candle STT 的 bf16 kernel 不在其架构门控内，**本地无法跑 STT**；TTS 走 torch（cu124 预置 sm_75 kernel），已在本地完整验证（7 段场景语音合成，RMS 0.036–0.113）。STT 与全链路在 4090 队列验证。

## 有记录的适配（执行补充，不改服务行为）

1. **配置本地化副本**（`interclarify-kyutai/configs/*.local.toml`）：`hf://` 模型路径替换为共享存储上 SHA-256 校验过的本地快照；`voice_folder` 指向本地 `tts-voices`；`static_dir`/`log_dir` 改绝对路径。STT `batch_size` 由 64 降为 8（单流交互场景的资源适配，吞吐远超 P1.2 需求）；
2. **TTS 嵌入 Python 环境**：运行期经 `PYTHONPATH`/`LD_LIBRARY_PATH` 暴露构建期 venv（与 unmute 的 `uv run` 等价）；
3. **缓存与镜像**：`HF_ENDPOINT=https://hf-mirror.com`；rust hf-hub 缓存与 python huggingface_hub 缓存分离存放于 `interclarify-kyutai/hf-{rust,py}-cache`（共享，作业节点复用）；
4. **端口与 GPU**：STT 31607、TTS 31608（与 `configs/base.yaml` 一致）；集群作业中 STT/TTS 跑在 GPU 1，官方控制模型跑在 GPU 0。

## 运行方式

- 手动/调试：`interclarify-kyutai/run/start_stt.sh [gpu] [port]`、`start_tts.sh [gpu] [port]`（日志在 `interclarify-kyutai/logs/`）；
- 集群作业：容器内由 [scripts/remote/start_kyutai_services.sh](../../scripts/remote/start_kyutai_services.sh) 拉起并等待就绪，再执行场景合成与 live-link 运行（见 [任务单 p1_2_live_link.md](../jobs/p1_2_live_link.md)）。

## 验收与风险

- 部署验收：STT/TTS 端口就绪、TTS 合成可出 24 kHz PCM、STT 对合成语音返回 Word 事件（本仓库 `scripts/prepare_p1_2_scenarios.py` 与 live-link 运行即覆盖）；
- 语言适配风险不变：STT 为英/法语料（与 DuplexCascade 官方底座一致），目标域中文需求触发 ASR/TTS 替换时，替换后的底座由所有后续策略共用（第 5.1 节）；
- 双 GPU 需求：单卡 24 GB 同时容纳 LLM（峰值约 17.2 GB）与 STT/TTS（约 5–7 GB）风险过高，作业默认申请 2 GPU（`submit_p1_2_job.sh` 可用 `P1_2_GPUS=1` 覆盖，此时 STT/TTS 与控制模型共享 GPU 0，仅建议调试使用）。
