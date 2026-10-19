# 文档与退役路线维护记录

更新：2026-10-19。当前入口为 [工程方案](engineering_implementation.md) 和 [issue 索引](issue/README.md)。

2026-10-16 已退役 Qwen3-ASR 服务、配置、旧联调作业与选型一次性工具，原因是回写与前缀冻结造成不可接受的交付停滞。清理前实现见 [6c75f38 快照](https://github.com/Vitalrubbish/InterClarify/tree/6c75f38d659998d6f149923085d82c0d7db267c5)。现有 X2、MOSS 及其脚本文档只说明仍存在的诊断实现，不作为新链路选型。

2026-10-18 用户指定 Nemotron EN 160ms + Kokoro，并开始投入训练方向。删除八份过时阶段计划与重复分析，保留的结论、运行来源和恢复位置见 [历史证据索引](baseline_evidence.md)。现存代码的同路径说明保留；ASR 原始报告和对齐记录、TTS 测量证据继续保留。没有删除远端资产、结果数据或现存代码。

2026-10-19 用户明确授权清理远端：Qwen3-ASR模型、专用环境、旧源码和ASR/TTS选型开发快照已删除；原始实验数据、现役Nemotron/Kokoro、训练环境与Kyutai参考保留。精确范围、恢复档及删除后验证见 [Issue 011](issue/archive/011_remote_storage_cleanup.md)和[执行记录](../reports/maintenance/20261019-retired-selection/README.md)。此为实际远端清理，不改写上两轮仅文档清理的历史。

同日012进一步归拢主目录：24个历史实验/维护目录已移入interclarify-archive，顶层可见目录50→26，旧目录位置不再保留链接；011恢复档也随维护目录迁移。原研究数据未删除，当前路径见 [012迁移记录](../reports/maintenance/20261019-home-consolidation/README.md)。
