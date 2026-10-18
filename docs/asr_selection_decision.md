# ASR 选择与 Layer 1 训练方向

更新：2026-10-18。用户已确定英文主线使用 **Nemotron Speech Streaming EN 0.6B / 160ms**，开始投入 Layer 1 小规模继续训练；TTS 配合使用 Kokoro。选型已定，接入和训练尚未验收。

## 实测依据

FLEURS 英文 100 条中，EN 160ms WER 为 7.68%，估计正确词交付 P50 为 414ms；Kyutai 为 21.97%、713ms。只统计正确且可对齐词，覆盖率不同；原始长尾和一次 EN 预热失败仍未归因。未观察到可见文本回写不能替代长会话稳定性验收。[原始报告](../reports/asr_selection/20261016-results/summary.md)

官方输入对齐后，EN 160ms 原样与去标点五例均为 0/5；Kyutai 为 5/5、3/5，相关请求通过 token 级审计。空格修复没有解除兼容问题，但词内增量、分拍、内容与时钟仍需有限诊断。整轮 320ms 分片异常，实际保留 98 条结果。[对齐记录](asr_official_input_retest.md)

## 当前执行方向

- 按固定配置接入 Nemotron，保留真实增量、到达时间、空窗与 EOF 生命周期，不规则补点。
- 从完整恢复的官方 checkpoint 继续训练现有 q/v LoRA，首轮冻结基础模型及 embedding/head；比较未训练、原样继续训练、用户侧去句读、混合增强。
- 同时覆盖接话和等待负例；数据按对话/说话人切分，既有 FLEURS 与 FDB 不训练。
- 先远端资源短跑，最多两轮小规模适配，以独立开发集接话、误抢话、附和、有效插话和内容质量决定继续或停止。
- Kyutai 只保留历史与官方权重对照，X2 只保留诊断；Qwen3-ASR 已退役。当前不重开 ASR 选型。

协议与研究边界见 [工程方案](engineering_implementation.md)，具体任务见 [issue 索引](issue/README.md)。
