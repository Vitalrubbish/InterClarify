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
- **离线样例已跑通**（2026-10-07，作业 `job-179138919006004209910-xuan-zhang`，`pdgpu-4090`）：4 个 micro-turn 的官方控制行为为 `talking → talking → finish talking(+回复) → interruption`；bf16 单卡峰值显存约 17.2 GB，`rtf_vs_micro_turn≈0.45`；证据 `interclarify-p0-artifacts/p1_offline/ic-20261007T160632-93c97783/`（`git_dirty=false`）。
- **P1.2 实时双工链路代码就绪**（2026-10-08）：无头双工 harness（`src/interclarify/realtime/`：时钟、单一播放所有者、场景、客户端）+ 官方 LLM 服务子进程启动器（`src/interclarify/duplex/official_server.py`）+ 入口 `scripts/run_p1_2_live_link.py` 与场景合成 `scripts/prepare_p1_2_scenarios.py` + 集群作业脚本 + 任务单 [p1_2_live_link.md](../jobs/p1_2_live_link.md)；本地 CPU 测试 31/31 通过。集群实跑待 Kyutai STT/TTS moshi-server 在作业节点部署后提交作业（前置条件见任务单）。


