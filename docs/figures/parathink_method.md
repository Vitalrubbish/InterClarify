# 架构图绘制说明

更新：2026-11-03。对应[图源](../../figures/parathink_method.tex)，合同见[架构第2节](../research_design/architecture.md#2-模块与动作边界)。NTF-017已同步原生控制、独立X2与160ms联合提交；图中下游接入、真实模型验证和CoT反馈仍是后续目标，不表示已接入。

后续用户已确认将 Layer 0 系统附和能力并入 Layer 1。本页其余内容解释合并前的图源与预览，图中独立 Layer 0 不再表示当前目标部署；当前文字合同见[架构设计](../research_design/architecture.md)，训练方案见[专项研究](../research_design/layer1_training.md)。本次研究未重绘图源或预览。

## 结构与绘图元素

TikZ源码没有运行时类或方法。frontend表示语音前端，box表示组件，wide表示Context和唯一输出路径，eventbox表示下游输出生命周期。flow表示读取与顺序消费，write表示提交，control表示读取已提交nonidle后的输出执行，thinking表示思考请求／CoT发布，future表示尚未实现的CoT反馈，feedback表示实际输出状态回传。

同源连续PCM送入两条独立路径：SoulX内部保留SenseVoiceSmall、音频编码、规则、反馈及reset；外部X2每160ms完成两个80ms LISTEN／DECODE步，真实EOS闭合组才提供正文。X2正文不注入SoulX状态KV，图中不再连接外部转写到控制器。

前端只用一条箭头向Context联合提交正文、五状态与真实进度。先完成结果暂存，WAIT无字也完成，提交成功后才允许下一批；不保存PCM，不标版本化转写。Context下方只并列Layer 0、Layer 1和Layer 2；它们在各自输入边界读当前完整快照，前端、表达和思考可以并发。

Layer 2只发布内部CoT，Layer 1负责表达与思考请求。点线表示未来CoT条件化控制；适配和训练尚未实现。NTF-020已取消归档；Layer 1在正常输入边界读到已联合提交的有效complete及当前正文后可开始普通回答，不再等待第二层ready。提交前内部状态不供下游使用，联合提交不代表尾词必齐。

## 打断与输出

图中已删除前端直达播放器的停止旁路；控制箭头从Context出发，表示下游先读取已联合提交的有效nonidle，核对活动output_id及preparing／playing生命周期，再由既有唯一输出运行时执行幂等停止。该路径不等待FIFO、TTS完成或当前LLM推理；本次没有接真实播放。

底部依次关闭旧output_id、停止并取消未播内容、取得实际关闭确认后发布Listen、读取后续已提交有效complete后开始新回答。Layer 0附和和Layer 1表达共用同一Text FIFO与TTS／播放器，其他状态不进入输出执行路径。已听内容不可撤销，真实生成与播放历史保留；本版不增加修订或回滚实现。

预览产物与编译方法见[预览说明](parathink_method_preview.md)。
