# P1 DuplexCascade 复现

P1 对应 [engineering_implementation.md](../engineering_implementation.md) 第 5 节。当前先实现 P1.1 的服务器资产准备，保持官方 ASR、LLM、TTS 和 micro-turn 路径不变；InterClarify 的 Layer 2 决策尚未接入。

## 已实现

- [sync_from_github.sh](../../scripts/remote/sync_from_github.sh)：服务器从 GitHub `main` 更新干净项目 checkout；
- [prepare_p1_assets.py](../../scripts/remote/prepare_p1_assets.py)：在服务器共享存储下载和校验固定官方代码、DuplexCascade 权重与基础模型；
- [submit_p1_assets_job.sh](../../scripts/remote/submit_p1_assets_job.sh) 与 [run_p1_assets_node_job.sh](../../scripts/remote/run_p1_assets_node_job.sh)：以 `pdcpu` 作业方式在集群执行资产下载（登录会话后台进程会被进程组清理，改由 `vc` 托管）；
- [P1.1 任务单](../jobs/p1_official_assets.md)：记录 GitHub 中转、conda 环境、Hugging Face 认证和验收证据。

## 进度

- Hugging Face token 已在服务器 `hf_token.txt`（已被 `.gitignore` 排除）就绪；gated 小文件下载验证通过，`train_cfg.json` 指向基础模型 `Qwen/Qwen2-7B-Instruct`（LoRA `qv`，r=16）。
- 集群到 `hf-mirror` 实测约 0.1–1.5 MB/s 且大文件会 `ChunkedEncodingError` 中断；改用 **ModelScope 镜像**（约 9–10 MB/s，支持 Range 续传）。ModelScope 的 `model_state.safetensors` SHA-256 与固定 HF revision 的 LFS blob 名完全一致（`603070a3…`），故内容与固定底座逐字节相同。
- 官方源码已固定在 `4289302`；DuplexCascade 权重（约 17.4 GB）与基础模型（约 15 GB）通过 `pdcpu` 作业下载中（`prepare_p1_assets.py --provider modelscope`）。
- 资产完成后继续实现固定最小输入的官方推理适配，并保存原始输出、GPU 峰值显存和实时因子（P1.1 剩余项）；实时 ASR–LLM–TTS 链路属于 P1.2。


