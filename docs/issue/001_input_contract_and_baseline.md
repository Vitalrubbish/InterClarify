# Issue 001：冻结输入契约、基线与验收口径

状态：待办。优先级：P0。依赖：无。完成后解锁 002–005。

## 问题与目标

官方空白对齐后 EN 160ms 仍为 0/5；本轮有关请求审计通过，但词内增量、分拍和起拍条件尚未分离。目标是在准备训练时收敛输入混杂，避免用训练掩盖接口错误。ASR/TTS 选择已定，不再开展候选普查。

## 已确定的训练路线

本轮使用官方论文采用的 UltraChat dataset，自行实现双工 micro-turn 数据生成管线，从完整官方 DuplexCascade checkpoint 继续训练。Qwen2-7B-Instruct 只作为官方 checkpoint 恢复所需的基础模型，不作为重新训练双工能力的独立初始化；本轮不设置从原始模型重训的实验臂。

## 工作项

- [ ] 盘点实际 X-Talk checkout、官方 checkpoint、基础模型、tokenizer、embedding/head、q/v LoRA 与发布配置，冻结 revision、文件摘要和许可证。
- [ ] 冻结 Nemotron 160ms、Kokoro 82M/af_heart、600ms micro-turn、BF16/实际精度、64-token 贪心生成及结束 ID；确认产品会话起拍与历史首非空起拍的差异。
- [ ] 复用固定轨迹核对 strip、空拍、BOS、ChatML、assistant 原始生成 IDs 与独立官方 oracle；审计逐请求 prompt IDs。
- [ ] 限定一次词内增量/完整词发布与时钟诊断，记录真实可见前缀。任何暂存只用已到达字符，必须明确刷新与超时并计入延迟；若不适用完整词发布，记录原因，不硬造对照。
- [ ] 记录原样 EN 160ms 官方权重失败基线，不向模型发送 EOF、标注边界或补句号；不把只改 prompt 审计理解成完全复现官方服务。
- [ ] 预登记训练对照、数据保留集、随机种子、最多两轮适配的步数/资源预算和验收规则，明确尚未冻结项的负责人及依赖。

## 拟交付物

`configs/layer1_adaptation_protocol.yaml` 与同路径 docs；诊断优先复用 `scripts/remote/retest_asr_official_input.py`，新增逻辑同步其说明。远端结果写独立 `data/runs/<run_id>/`，紧凑报告写 `reports/layer1_training/<run_id>/`。

## 测试与完成条件

- [ ] 固定轨迹逐请求输入审计零不一致，错误有原始 IDs 与首次差异位置。
- [ ] 提供分拍、到达、生成历史及正文启动的逐例对照，区别协议错误、持续等待、提前正文和旧回答续写。
- [ ] 所有参数/摘要及诊断退出码可复核；没有遗留会污染训练的数据格式问题。
- [ ] 冻结清单明确 UltraChat 来源、由本项目实现的生成器、官方 checkpoint/tokenizer/base/embedding/head/LoRA 摘要及组间共享条件；无法取得的作者精确样本清单标明未知。
- [ ] 若发现必须改变线上前缀交付的行为，先更新工程文档，再实现并重测。

本 issue 不要求官方权重接话达标才允许训练。诊断目的在于确认真实输入契约，不能无限延长或重新选型。
