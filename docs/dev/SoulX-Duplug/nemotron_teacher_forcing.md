# Nemotron 与 SoulX 的160ms工程同步方案

2026-10-30。用户已授权实现与远端 FDB 小样本测试。Nemotron提供唯一的用户转写，SoulX 0.6B预测五类状态；两份模型权重固定，以逐块同步屏障推进。实现进度见[工作单](../../issue/README.md)。

## 1. 模型与输入

Nemotron沿用EN0.6B revision `ebe59e5a817142986528bbbee5dba8db7b38ed50`、FP32、lookahead1，每步处理160ms新增音频并保留RNNT缓存。取消SoulX的3.2秒ASR重识别窗口、文字差分及SenseVoice整段识别。SoulX音频编码仍使用原有回看与前瞻。

每块以步骤编号和真实采样区间配对，另记实际观察上界；名义步骤编号不能代替真实解码完成，也不能证明本步返回的词只来自当前160ms。

本次用户授权先修配对：旧实现将原生ASR首块92.5ms与SoulX首块160ms按同一步号配对，造成后续观察截止持续落后61ms。改为首块只初始化RNNT缓存并单独释放，取实际ASR完整窗口覆盖达到SoulX主块截止的第一个完成步骤，首块正文保留到首次教师注入。两路独立计步，典型配对160→259ms、320→419ms；99ms额外观察如实计入前瞻与延迟。原生窗口不改形状，音频接收继续真实时钟进行。尾部不足下一真实ASR窗口时不产生新在线状态，排空只诊断。本次不修改任何完成规则，见[NTF-003](../../issue/NTF-003.md)。

## 2. 同步流程

```text
本步音频 → Nemotron完成本步解码 → 取得新增文字（允许为空）
         → 0.6B输入音频、教师文字、ASR结束符 → 预测状态
         → 联合发布Context → 释放屏障 → 双方推进下一块
```

SoulX可提前准备音频embedding，但最终状态必须在本步教师文字注入后预测。普通自生成文字不反馈KV；教师文字使用SoulX tokenizer编码，不受0.6B原有文字门控阻塞，不重复注入旧前缀，也不给词内增量补空格。

有效状态在下一次模型前向中输入一次。状态位置的普通文字或未知special token记为无效输出，不通过自由生成凑出一个状态。

音频接收和有限预缓冲持续进行，以满足前瞻；屏障仅限制解码推进。现有ASR服务的完成回调涉及特征迭代器与streamer配对，接入时须核查真正可暂停的单步边界，防止预取已推进下一块或等待前瞻造成死锁。

## 3. 两种上下文

| 位置 | 内容 |
| --- | --- |
| 0.6B内部输入／KV | 音频embedding、Nemotron教师文字、结构分隔符、用户状态 |
| SharedContext | Nemotron原始累计正文与独立字段中的当前有效状态 |

下游仅接收idle、nonidle、incomplete、complete、backchannel五类用户状态。ASR结束符、padding和音频边界符只用于内部结构。每个处理步联合覆盖最新正文与状态，保留现有160ms当前值接口。

## 4. 空增量、reset与收尾

ASR完成但无新字是合法步骤；尚未完成记为pending。同步屏障消除未完成导致的错位，不保证每步出字，也不提前回填晚到词。

原生规则在连续三帧原始预测nonidle且delta为空时，强制从complete／incomplete中选择；这不是三帧静音。建议单独消融该计数分支，并区分另一条nonidle转idle触发分支。SenseVoice六视图的269帧中已有9帧nonidle转incomplete、2帧转complete；这些是规则干预计数，不等于11个语义错误。

SoulX reset不重启Nemotron、不清空共享正文、不重复消费旧字。本轮明确使用软重置：保留本逻辑话轮的音频／教师文字 KV、待输入的有效状态和教师字符游标，仅清理发声及等待计数；话轮结束才释放 KV。原因是硬清空后不能既保留语义又避免重注入旧前缀。上下文设 token 上限，触限明确失败。complete使用已交付正文，不触发整段ASR，也不证明尾词已到达；EOF排空仍按现行接口单独诊断。

教师文字逐次按原始字符增量编码，不重新分词或回写已注入片段，不补空格；拼接的解码结果须与原始累计文字一致。ASR 的真实特征窗口、解码开始／完成、教师注入、状态完成、发布及释放时刻均留在外部审计文件中，SharedContext 只存当前值。主实验沿用原生两条完成规则，另提供关闭连续空增量计数分支的选项，nonidle→idle 分支独立记录。

## 5. 验收与依据

本轮实现及远端三轴30条已完成：3185帧真实同步顺序复查通过，在线WER停顿12.85%、打断8.47%；接话覆盖增加但停顿complete与打断nonidle指标变差，状态语义未整体通过，详见[报告](../../../reports/soulx/20261030-nemotron-teacher-fdb30/README.md)。完成工作单已归档，不继续占用远端作业。

检查每块ASR完成、教师文字注入、状态完成、联合发布及下一块解码开始的实际顺序；同时核对文字消费一次、词内增量、reset、尾词和状态时机。原始预测与规则改写分别记录，不能仅用步骤编号一致或最终全文可读判定通过。

真实时钟回放沿用单作业、1×4090、4CPU、32GiB、显存22GiB、结果128MiB及800ms积压停止线。音频持续到达，计算吞吐不足时如实失败，不放慢回放掩盖积压。

依据：[SoulX推理源码](https://github.com/Soul-AILab/SoulX-Duplug/blob/a0b9063843df69619b087b95b74597b2176910b8/service/model.py)、[token定义](https://github.com/Soul-AILab/SoulX-Duplug/blob/a0b9063843df69619b087b95b74597b2176910b8/config/config.py)、[Nemotron固定版本](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b/blob/ebe59e5a817142986528bbbee5dba8db7b38ed50/README.md)、[独立ASR服务](../../scripts/remote/nemotron_asr_service.md)、[SenseVoice实测](../../../reports/soulx/20261030-delta-context-test/README.md)、[旧组合失败分析](nemotron_completion_analysis.md)。
