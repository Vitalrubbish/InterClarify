# 工程实施计划

更新：2026-11-03。第一阶段 ASR-Frontend 已完成，当前路线为 **SoulX-Duplug 官方配置＋并行 X2Streaming-ASR**。前端工作收口，后续 LLM 接入按用户指令暂缓。

## 1. 当前目标与运行底座

SoulX 保留内部 SenseVoice 教师、门控、滑窗差分／KV 修订、状态规则、反馈和原生 reset；X2 只为 SharedContext 提供独立正文，不将外接转写注入状态 KV。两路读取同一持续 PCM。每 160ms 批次等 X2 完成两个 80ms 原生步及其组内解码、SoulX 完成本步原生调用后，将 EOS 闭合正文和状态 token 一次写入 SharedContext；提交成功后才允许下一步。先完成结果只在内部暂存，不写原始 PCM。

五状态统一经过本批次联合提交，不设置前端 nonidle 专用停止钩子。已提交的有效 complete 携当前正文直接供 Layer 1 在当前 turn 使用，无需额外交接等待；同步不保证尾词必齐。详细合同见[独立前端](dev/SoulX-Duplug/independent_streaming_frontend.md)及[Context 接口](dev/SoulX-Duplug/shared_context_interface.md)。

现役 Agent 底座见[运行配置](runtime_baseline.md)，本次不切换。官方源码使用[固定子模块及远端 checkout](third_party/soulx-duplug.md)。

## 2. 工作顺序与交付

| 顺序 | 工作单 | 交付与状态 |
| --- | --- | --- |
| 1 | [NTF-015](reports/soulx/20261102-native-independent-frontend/README.md) | 已完成：原生协议控制封装、冻结加载器、状态来源与 reset 审计 |
| 2 | [NTF-016](reports/soulx/20261102-native-independent-frontend/README.md) | 已完成：同源 PCM、X2 原生 80ms 适配、160ms 屏障、EOS 正文／真实进度回调 |
| 3 | [NTF-017](reports/soulx/20261102-ntf017-joint-publication/README.md) | 已完成：联合提交、停止旁路撤回、短锁生命周期和图源同步 |
| 4 | [NTF-018](reports/soulx/20261103-ntf018-warmup/README.md) | 已完成：完整预热、有限预热对照和单路参考，预检 3/3、退出 0 |
| 5 | [NTF-019](reports/soulx/20261103-ntf019-fdb30/README.md) | 已由用户审核通过并归档，原始运行与限制保留 |
| 6 | [NTF-030](reports/soulx/20261103-latency-limit-removal/README.md) | 已取消 800ms 时长停止条件，169 项本地检查通过 |

前端工作已收口，无活动接入任务。两路每批联合写 Context 后推进，不等待消费者；原生 reset 不清正文，生产者持续到达，所有时标与 EOF 尾部独立报告。

## 3. 资源与执行边界

本地和远端使用已有 conda，真实模型测试仅在远端调度作业运行。逐文件同步 docs 中文说明，解释功能、类和核心方法；不复制权重或修改共享环境。

原生前端保持单活动作业、1×4090、4CPU、32GiB RAM、batch=1，显存 22GiB 停止线；每路 worker 各 1，CPU 线程各 ≤2。未读 PCM 时长、墙钟积压、送音迟到及发布延迟只记录，不按 800ms 停止；PCM 总量仍 ≤4MiB。启动空闲盘 ≥10GiB，每作业 ≤1800 秒、输出 ≤128MiB，资源触限保留失败，不自动放慢送音、丢帧或扩大资源。

## 4. 后续边界

用户已确认将 Layer 0 系统附和能力并入 Layer 1；训练目标、因果数据与分阶段学习思路见[训练设计](research_design/layer1_training.md)，不单独部署附和预测器。研究包含真实控制噪声、首音前取消和开播后恢复；具体协议、训练参数与资源安排在实施阶段确定，未启动语料生成、训练或 LLM／TTS 接入。

普通回答生成边界、单一输出执行点及 TTS 播放所有权保持；状态统一经联合快照交付，撤回前端专用停止旁路。后续 CoT 条件化控制目标仍见[架构第 2.5 节](research_design/architecture.md#25-soulx-的-cot-条件化控制)，本次不构造训练数据或注入 CoT。图源及 PDF／PNG 已由 NTF-017 同步；不表示回答或播放链路已实现。

160ms 推进合同见[设计第 2.1 节](dev/SoulX-Duplug/independent_streaming_frontend.md#21-每160ms音频步的推进屏障)，NTF-015／016 已实现计算基础，NTF-017 已完成联合发布迁移。后续工作待用户另行明确指令。
