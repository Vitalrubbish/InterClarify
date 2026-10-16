# ASR 实验与退役路线清理

日期：2026-10-16。清理原因是选型测试已经结束，Qwen3-ASR 的回写与前缀冻结机制不满足对话延迟要求。工程约束以 [工程方案](engineering_implementation.md) 为准，后续方向见 [选型决定](asr_selection_decision.md)。

## 保留的证据

- [最终比较报告](../reports/asr_selection/20261016-results/summary.md) 与同目录原始 JSON、单轮和重复轮汇总；保留 `complete=false`、预热失败及未解释长尾。
- `reports/asr_selection/20261016-smoke25/`、`reports/asr_contract/` 和 `reports/duplex_acceptance/` 原样保留。
- [Qwen 延迟诊断](fdb_latency_diagnosis.md)、[Qwen 复测结果](asr_measurement_retest.md)、[X2 复测记录](x2streaming_asr_retest.md) 与阶段 A 历史证据保留，不再作为执行旧任务的指令。

## 移除的实现与说明

移除选型准备、独立对齐、基准测量、分片提交、汇总、日志探针、接话轨迹准备与重放、旧 ASR 契约 A/B 工具，以及对应单测和 `docs/` 镜像说明。移除已完成的选型任务单与候选普查，不维护其后续运行步骤。测试方法、指标限制与来源仍见结果报告和 Git 历史。

移除 Qwen3-ASR HTTP 服务、专属单测、两个 Qwen 运行配置及旧 round-one 作业入口。通用模型准备脚本删除 Qwen 下载配置、ASR smoke、依赖检查和启动分支；从源码镜像配方移除 Qwen 源码与 conda 环境。已发布镜像的历史内容不因此改变，旧 overlay 只用于复现历史依赖层，不会清除底层已有的 Qwen 环境。

保留 X2 服务、环境准备、双工配置与 A4 驱动，必须显式选择 X2 并提供资产。它仅用于已有链路回归，不能代替 Nemotron 主线接入。保留唯一控制执行者与 TTS 播放所有权。

## 恢复与边界

清理前源码快照为 [`6c75f38`](https://github.com/Vitalrubbish/InterClarify/tree/6c75f38d659998d6f149923085d82c0d7db267c5)。历史文档中的已删除文件链接改指该快照；结果目录内容不改写。需要复核旧实验时从历史提交建立独立 checkout，使用原始来源和 conda 记录，不将退役路径恢复为默认配置。

本次只清理 InterClarify 跟踪的文件，不删除远端权重、conda 环境、运行目录或独立维护的 X-Talk fork 源码。已有用户对 `AGENTS.md` 的修改不纳入本次提交。

## 清理验证

在已有 conda 环境 `paratalker-dev` 中运行本仓库离线回归：74 项，54 通过、20 跳过；跳过项依赖本环境未安装的 torch 或 MOSS 上游，不代表真实模型验收。Python 编译、修改的 Bash 脚本语法、CLI 可用子命令、源码 manifest 生成与差异空白检查通过。131 份已跟踪报告逐文件与清理前 Git 内容摘要相同；保留 Markdown 无指向本次删除文件的本地链接。未提交新的集群作业，未重建或发布镜像。
