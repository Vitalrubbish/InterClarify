# P1 DuplexCascade 复现

P1 对应 [engineering_implementation.md](../engineering_implementation.md) 第 5 节。当前先实现 P1.1 的服务器资产准备，保持官方 ASR、LLM、TTS 和 micro-turn 路径不变；InterClarify 的 Layer 2 决策尚未接入。

## 已实现

- [sync_from_github.sh](../../scripts/remote/sync_from_github.sh)：服务器从 GitHub `main` 更新干净项目 checkout；
- [prepare_p1_assets.py](../../scripts/remote/prepare_p1_assets.py)：校验仓库内 3rd-party/DuplexCascade 的固定官方代码，并在服务器共享存储下载和校验 DuplexCascade 权重与基础模型；
- [submit_p1_assets_job.sh](../../scripts/remote/submit_p1_assets_job.sh) 与 [run_p1_assets_node_job.sh](../../scripts/remote/run_p1_assets_node_job.sh)：以 `pdcpu` 作业方式在集群执行资产下载（登录会话后台进程会被进程组清理，改由 `vc` 托管）；
- [official_control.py](../../src/interclarify/duplex/official_control.py)：官方控制模型的薄离线适配器（复用官方 `model.py` 与 `server.py` 的 token/提示词逻辑，不改权重、不加 Layer 2）；
- [run_p1_offline_sample.py](../../scripts/run_p1_offline_sample.py) + [submit_p1_offline_job.sh](../../scripts/remote/submit_p1_offline_job.sh)：固定文本 micro-turn 离线样例的入口与 GPU 作业；
- 任务单：[P1.1 资产](../jobs/p1_official_assets.md)、[P1.1 离线样例](../jobs/p1_offline_sample.md)。

## 进度

- **P1.1 资产准备完成**（2026-10-07，作业 `job-179138059345760136585-xuan-zhang`，`pdcpu`）：官方源码 `4289302`；DuplexCascade 权重 17.4 GB，SHA-256 `603070a3…` 与固定 HF revision 的 LFS blob 一致；基础模型 `Qwen/Qwen2-7B-Instruct` 就位；证据 `interclarify-p0-artifacts/p1_assets/20261007T134316Z/`。
- `hf-mirror` 在本集群不可用（约 0.1–1.5 MB/s 且大文件中断），改用 ModelScope 镜像（约 9–10 MB/s，Range 续传，逐文件 SHA-256 校验）。
- **离线样例适配器已实现**（`official_control.py` + `run_p1_offline_sample.py`），CPU 单元测试覆盖控制 token 与提示词拼装；待提交 `pdgpu-4090` 作业运行并回收原始输出、GPU 峰值显存与 RTF。
- 实时 ASR–LLM–TTS 链路属于 P1.2。


