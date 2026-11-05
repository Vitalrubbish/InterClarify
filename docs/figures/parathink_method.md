# 架构图绘制说明

更新：2026-11-06。对应[图源](../../figures/parathink_method.tex)，合同见[架构设计](../research_design/architecture.md)。图示采用当前原生 SoulX＋独立 X2 前端、Layer 1 表达与附和、Layer 2 异步思考，以及唯一输出执行点。前端已有验收结果，下游与 CoT 条件化控制仍是待实现目标。

按用户要求，图中各框仅保留模块或步骤名称，删除标题下方的叙述文字、前端批次说明、并发说明及图底附注，收紧框体和纵向间距。连接关系及必要的箭头标签保留；详细职责和约束在本文及架构设计中说明。

## 结构与绘图元素

TikZ 源码没有运行时类或方法。frontend 表示语音前端，box 表示组件，wide 表示 Context 和唯一输出路径，eventbox 表示输出生命周期。flow 表示读取与顺序消费，write 表示提交，control 表示下游读取有效 nonidle 后执行停止，thinking 表示思考请求／CoT 发布，future 表示待实现的 CoT 反馈，feedback 表示实际输出状态回传。

同源连续 PCM 送入两条独立路径：SoulX 保留 SenseVoiceSmall、音频编码、规则、反馈及 reset；X2 每 160ms 完成两个 80ms LISTEN／DECODE 步，以真实 EOS 闭合组提供正文。X2 正文不进入 SoulX 状态 KV。

两路通过一条箭头向 Context 联合提交正文、五状态与真实进度。先完成结果暂存，WAIT 无字也完成，提交成功后才允许下一批。Layer 1 和 Layer 2 在各自输入边界读取完整快照；前端、表达和思考可以并发。

Layer 1 统一负责等待、附和时机与措辞及正式回答，读取已提交的有效 complete 和当前正文后可在当前 turn 生成普通回答。Layer 2 只发布内部 CoT，不提供话轮建议或候选表达。点线表示未来 CoT 条件化控制，训练与适配尚未实施；同步完成不证明尾词齐备。

## 打断与输出

下游从 Context 读取已提交的有效 nonidle，核对活动 output_id 与 preparing／playing 生命周期，由唯一输出执行点进行幂等停止。停止不等待 FIFO、TTS 完成或当前 LLM 推理。

底部依次关闭失效 output_id、停止并取消未播内容、取得实际关闭确认后发布 Listen、读取后续有效 complete 后开始新回答。Layer 1 的附和与正式表达共用同一 Text FIFO 和 TTS／播放器。已听内容不可撤销，真实生成及播放历史保留。

[PDF／PNG 构建方法](parathink_method_preview.md)与图源同步；图示不表示已实现下游接入或真实播放。
