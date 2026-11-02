# 架构图绘制说明

更新：2026-11-03。对应[图源](../../figures/parathink_method.tex)，合同见[架构第2节](../research_design/architecture.md#2-模块与动作边界)。NTF-017已同步原生控制、独立X2与160ms联合提交；图中回答交接、真实模型链路和CoT反馈仍是后续目标，不表示已接入。

## 结构与绘图元素

TikZ源码没有运行时类或方法。frontend表示语音前端，box表示组件，wide表示Context和唯一输出路径，eventbox表示下游输出生命周期。flow表示读取与顺序消费，write表示提交，control表示读取已提交nonidle后的输出执行，thinking表示思考请求／CoT发布，future表示尚未实现的CoT反馈，feedback表示实际输出状态回传。

同源连续PCM送入两条独立路径：SoulX内部保留SenseVoiceSmall、音频编码、规则、反馈及reset；外部X2每160ms完成两个80ms LISTEN／DECODE步，真实EOS闭合组才提供正文。X2正文不注入SoulX状态KV，图中不再连接外部转写到控制器。

前端只用一条箭头向Context联合提交正文、五状态与真实进度。先完成结果暂存，WAIT无字也完成，提交成功后才允许下一批；不保存PCM，不标版本化转写。Context下方只并列Layer 0、Layer 1和Layer 2；它们在各自输入边界读当前完整快照，前端、表达和思考可以并发。

Layer 2只发布内部CoT，Layer 1负责表达与思考请求。点线表示未来CoT条件化控制；适配和训练尚未实现。普通回答还须NTF-020交接ready，原始complete或160ms屏障完成不能单独放行。

## 打断与输出

图中已删除前端直达播放器的停止旁路；控制箭头从Context出发，表示下游先读取已联合提交的有效nonidle，核对活动output_id及preparing／playing生命周期，再由既有唯一输出运行时执行幂等停止。该路径不等待FIFO、TTS完成或当前LLM推理；本次没有接真实播放。

底部依次关闭旧output_id、停止并取消未播内容、取得实际关闭确认后发布Listen、在后续ready交接下开始新回答。Layer 0附和和Layer 1表达共用同一Text FIFO与TTS／播放器，其他状态不进入输出执行路径。已听内容不可撤销，真实生成与播放历史保留；本版不增加修订或回滚实现。

预览产物与编译方法见[预览说明](parathink_method_preview.md)。
