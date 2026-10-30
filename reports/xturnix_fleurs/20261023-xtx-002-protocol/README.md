# XTX-002：Nemotron/XTurnix 协议与环境冻结

2026-10-23。状态：远端环境准备、模型冻结与 dev 协议探针完成；本阶段不运行正式 FLEURS 回放，不计算 start 延迟或 WER。

## 结论

- Nemotron EN160 FP32 与 XTurnix-PT 分别在隔离 conda 环境中加载；ASR 由现役原生流式服务提供，XTurnix 以官方 `turn_pipeline.py` 在独立进程内加载。
- 两个组件均在调度 GPU 作业中完成真实推理并正常退出，登录节点未运行模型。
- dev 探针的 21 项检查全部通过：原生输出、暂停恢复、EOF 排空、会话清理、Listen 动作、分数归一、去标点、上下文上限和资源峰值。
- 本轮按冻结协议不注入 `<|pause|>`；正式回放只能由 ASR 文本版本变化触发判断。
- FLEURS dev 的 Listen 调用均返回 `<|keep|>`，完整末句的 start 分数为 0.243；模型卡完整问句返回 `<|start|>`（0.613），证明 start 路径本身可用。该现象留待 XTX-006 用正式分母测量，不据此调阈值。

## 冻结版本

| 项目 | 冻结值 |
| --- | --- |
| ASR | `nvidia/nemotron-speech-streaming-en-0.6b`，revision `ebe59e5a817142986528bbbee5dba8db7b38ed50` |
| ASR 权重 | `model.safetensors` SHA256 `bddd8a7300826efd19cf7e01f1c7db8402bed6786fc4c7739632894f69c71473` |
| ASR 运行 | EN160、lookahead 1、FP32、单活动流；80ms PCM16 传输，160ms 模型分块 |
| XTurnix | `xcczach/xturnix-pt`，revision `d4b0403e5a6744b46fa7602b6d77bbac2768d5b5` |
| XTurnix 资产 | 21 个文件，1,208,053,095 字节；逐文件摘要见 `xturnix-pt.lock.json` |
| 环境 | Python 3.12.15、torch 2.11.0+cu128、transformers 4.57.1、tokenizers 0.22.2 |
| 配置 | `archive/configs/xturnix_fleurs_test.json`，SHA256 `ae121007859ab3d7c6d07d38688082bffb0a6803cda3490b0c8b34f6b111fb43` |
| 源码 | 环境准备 `470b3c0`；探针运行 `701e6209a5d462b79041b2f0aff9c50a9ebdc852` |

环境从现役 ASR seed 克隆为 `~/interclarify-xturnix-fleurs/envs/xturnix`，仅在隔离环境内把 Transformers 固定到 4.57.1；未升级或覆盖现役 ASR/TTS/评分环境。模型只读复用 `~/interclarify-asr-selection/models/nemotron_en`。

## 协议冻结

| 项目 | 值 |
| --- | --- |
| Listen 合法动作 | `<|start|>`、`<|keep|>`；两动作分数取最大值 |
| 归一化 | 仅去最后一条用户消息末尾 Unicode 标点及相邻空白；保留内部标点、大小写和原始 ASR |
| 上下文 | 官方 `max_seq_length=2048`；放不下末条用户消息时失败，不静默截断 |
| ASR 结果轮询 | 50ms；单请求超时 30s；单活动会话；30s 有界音频积压 |
| 控制调度 | 单会话最多一个在途请求；排队容量 1；保留最新前缀，丢弃未开始的旧观察；请求超时 10s |
| 停顿 | `pause.enabled=false`；不从 EOF、文件时长、参考文本、离线末 token 或事后对齐补点 |
| 回放合同 | 影子 Listen；start 不关闭 ASR；5 秒静音尾窗；5 秒主窗口；EOF 仅排空 |

停顿禁用的原因是冻结的 Nemotron 服务没有可直接使用的因果分段事件，而独立 VAD 不在 XTX-002 范围内。未来启用 `<|pause|>` 必须先冻结并验证因果 VAD 或真实上游分段事件。

## dev 协议证据

作业 `job-179273870968613116050-xuan-zhang` 运行于 `d6-hpc-gpu-054`，GPU 为 RTX 4090 24GB；探针从 `06:59:22Z` 到 `06:59:50Z`，退出码 0。全部证据保存在：

```text
~/interclarify-xturnix-fleurs/runs/xtx-002-probe-20261023-r3/
```

| 检查 | 结果 |
| --- | --- |
| ASR 健康、模型、160ms、FP32、两次预热 | 通过 |
| 原生文本非空、版本前缀单调 | 通过；28 个观察版本，末版本 56 |
| 录音中点暂停后继续输出 | 通过；暂停前缀到完整末句增长 |
| EOF 排空与 DELETE 清理 | 通过；删除后结果接口 404 |
| 第二会话创建、结束、清理 | 通过；清理后服务仍健康 |
| Listen 动作与分数 | 通过；所有调用只返回 start/keep，分数和为 1 |
| 去标点与内部标点保留 | 通过；`Hello, world.` → `Hello, world`、`Wait...  ` → `Wait` 等 |
| 超长上下文失败可见 | 通过；报 `cannot fit max_length` |
| Speaking 动作 | 通过；返回 `<|stop|>`（0.920656） |
| 模型卡完整问句 | 通过；返回 `<|start|>`（0.613420） |

ASR 最终文本为：

```text
In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country
```

该 dev 文本的三段前缀与完整文本在 Listen 下均返回 `<|keep|>`；完整文本的 `<|start|>` 分数为 0.243409。由于本轮不注入停顿 token、也不在静音尾窗重复推理，不能把该结果解释为正式 start 命中率。正式回放仍按 ASR 文本更新触发，提前 start、旧前缀迟到、窗口外和 EOF 后结果分别记录。

## 资源

| 项目 | 实测 |
| --- | --- |
| ASR 加载 | 31.96 秒，峰值 RSS 1,797,968 KiB |
| XTurnix 加载 | 3.05 秒，峰值 RSS 4,027,968 KiB |
| XTurnix GPU 峰值 | allocated 2,461,923,328 B，reserved 2,608,857,088 B |
| `nvidia-smi` 峰值 | 5,856 MiB；GPU 总显存 24,564 MiB |
| 准备磁盘 | 893.92 → 893.91 GiB 可用 |
| 新增 apparent 资产 | 环境 7,979,168,017 B＋模型 1,208,079,835 B，合计约 8.56 GiB |
| 运行证据 | 240 KiB |

`apparent` 计入 conda 硬链接的 apparent 大小；实际磁盘占用变化约 0.01 GiB。环境、模型与运行证据均低于 10 GiB / 2 GiB 上限，峰值显存低于 24 GiB 上限。

## 失败路径与修正

- 首次作业因 ASR `/health` 返回 `torch.float32`、而探针只接受 `float32` 而失败；改为接受 `torch.` 前缀后重跑。
- 另一次通过配置检查但未包含控制输入序号和 start 诊断，随后补入 `input_version` / `input_sha256` 与 `contract_example` 并完成最终 r3。
- r1、r2 的失败已记录；清理时删除其运行目录与提交日志，只保留最终 r3 证据。

## 证据摘要

| 文件 | SHA256 |
| --- | --- |
| `environment/xturnix_fleurs_test.json` | `ae121007859ab3d7c6d07d38688082bffb0a6803cda3490b0c8b34f6b111fb43` |
| `environment/model_verification.json` | `5b524ab438ff22ee4c5314852c9583a7f785333c9523d1439698ec7a45b836aa` |
| `environment/prepare_report.json` | `30449213d048ac763446799e465fb04d844402933b51e46e4d08c847dfc1e0b7` |
| `environment/verify_report.json` | `0bd61abf1d2ca66c9f6241d7343c8b5545af042df8b15344ae310e727397e279` |
| `models/xturnix-pt.lock.json` | `12184c9bde1968d33fd170a3b1fdc1c5685496e16d31df52819ef549ee7ee851` |
| `xtx-002-setup.log` | `81209f4b741178dc310a327abf5c0f00f2299219447a8d00ad34eef79fc52d31` |
| `runs/.../probe/probe.json` | `62f4bad887a89177d71479ba00027dba6cf35fcb50035722e17c4a6345e7894f` |
| `runs/.../probe/asr_evidence.json` | `2ba116010777af165538e39036c4ce245a8a40663832f908aeff8526dee993f5` |
| `runs/.../probe/xturnix_evidence.json` | `bbfdd36d47b846bf9f6058d3f47703dc999c649ac1129a28c2094b1df9cb7a51` |
| `runs/.../health.json` | `75c91a1b18cf427e45faf6f4bfeeee9ea8bf28f48996649f41bd076421748a0e` |
| `runs/.../service.log` | `78e38e1a89bc34ce5ede27d2fda773fb6c7a92b15839d5b5642a719c0aa275d5` |
| `runs/.../probe.log` | `8915b94ffeb98a57a7fef3cce219c93d139f23c29a03105a583594b57215d095` |

## 边界

本报告只证明 XTX-002 的组件加载、协议字段和 dev 路径可复核。它不证明 FLEURS 末端 start 命中率、控制延迟、WER、链路估计或真实话轮质量；这些分别由 XTX-003—006 执行。探针不训练、不调阈值、不修改现役环境、不接入 Layer 1/TTS/播放器，也不把影子 start 实际执行。

脚本说明见 [setup_xturnix_env](../../../docs/archive/scripts/remote/setup_xturnix_env.md)；配置说明见 [xturnix_fleurs_test](../../../docs/archive/configs/xturnix_fleurs_test.md)。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/xturnix_fleurs/20261023-xtx-002-protocol/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
