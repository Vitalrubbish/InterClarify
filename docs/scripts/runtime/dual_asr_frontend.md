# 双ASR有界配对

对应`scripts/runtime/dual_asr_frontend.py`。`PairedPublisher`是唯一Context帧写者，`submit_state()`与`submit_step()`只冻结并排队。状态按主块截止连续递增，Nemotron步骤按自身序号和真实窗口上界连续递增；`publish_ready()`取首次覆盖状态实际观察上界的步骤，使用该步骤正文而非最新全文。模型调用和Context提交不占队列锁。

首个状态允许不足2560的真实主块，之后每步严格增加2560；冻结官方启动实际为1920、4480等截止。首块合成padding只在音频账本中记录，不计入真实截止。待发布跨度从首个待发布主块真实起点计算。

队列硬上限与失败合同见[方案](../../dev/SoulX-Duplug/dual_asr_publication.md)。超过条数、字节、800ms待发布跨度或真实覆盖不合法立即抛错。`diagnostics()`输出未发布状态和各队列占用；`close()`保留最后当前值并清空队列，之后拒绝入队。Context只保存正文与状态当前值，控制文字和两路窗口审计位于外部文件。

`DualASRFrontend`通过继承原生前端恢复SenseVoice控制路径；将完成的状态交给配对器，不直接发布SenseVoice正文。官方reset、门控、滑窗及即时nonidle停止均由已有前端执行，不使用教师soft reset。
