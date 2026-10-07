# P1 DuplexCascade 复现

P1 对应 [engineering_implementation.md](../engineering_implementation.md) 第 5 节。当前先实现 P1.1 的服务器资产准备，保持官方 ASR、LLM、TTS 和 micro-turn 路径不变；InterClarify 的 Layer 2 决策尚未接入。

## 已实现

- [sync_from_github.sh](../../scripts/remote/sync_from_github.sh)：服务器从 GitHub `main` 更新干净项目 checkout；
- [prepare_p1_assets.py](../../scripts/remote/prepare_p1_assets.py)：在服务器共享存储下载和校验固定官方代码、DuplexCascade 权重与基础模型；
- [submit_p1_assets_job.sh](../../scripts/remote/submit_p1_assets_job.sh) 与 [run_p1_assets_node_job.sh](../../scripts/remote/run_p1_assets_node_job.sh)：以 `pdcpu` 作业方式在集群执行资产下载（登录会话后台进程会被进程组清理，改由 `vc` 托管）；
- [P1.1 任务单](../jobs/p1_official_assets.md)：记录 GitHub 中转、conda 环境、Hugging Face 认证和验收证据。

## 进度

- **P1.1 资产准备完成**（2026-10-07，作业 `job-179138059345760136585-xuan-zhang`，`pdcpu`）：
  - 官方源码固定在 `4289302`；
  - DuplexCascade 权重（17.4 GB）SHA-256 = `603070a3…`，与固定 HF revision `31c038e…` 的 LFS blob 一致，`matches_pinned_sha256=true`；
  - 基础模型 `Qwen/Qwen2-7B-Instruct`（ModelScope revision `8dce1f8a…`）与 tokenizer 就位；
  - 证据：`interclarify-p0-artifacts/p1_assets/20261007T134316Z/`（`manifest.json` status=PASS）。
- `hf-mirror` 在本集群不可用（约 0.1–1.5 MB/s 且大文件中断），改用 ModelScope 镜像（约 9–10 MB/s，Range 续传，逐文件 SHA-256 校验）。
- **下一步（P1.1 剩余）**：基于固定最小输入实现官方推理的薄适配器，保存原始输出、GPU 峰值显存和实时因子；实时 ASR–LLM–TTS 链路属于 P1.2。


