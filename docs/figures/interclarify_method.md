# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-23。

## 整体作用

展示共享 Context、独立话轮控制、并行思考与表达，以及用户打断时的停止和恢复流程。按用户确认的方案，补充绕过 Text FIFO 的优先控制路径、输出标识失效和实际停播确认，并据此同步[架构文档](../research_design/architecture.md)。原因是仅清空文本队列无法阻止已经进入合成、音频缓冲和在途任务的旧输出。

图中保留 Layer 0/1 直接提交 Text FIFO 的结构，不新增独立 Arbiter 模块；唯一仲裁执行点位于输出运行时，统一管理队列、TTS 和播放器。图与文档描述目标合同，不代表打断链路已经实现或通过验证。本次不创建工作单或运行远端作业。

按用户确认的职责调整，Layer 2 标注为仅发布 CoT，XTurnix 标注为负责全部话轮决策。移除将 Layer 2 发布理解为介入建议的歧义，避免任务分析与话轮策略重复承担动作监督。

## 结构与绘图元素

文件为 TikZ 绘图源码，没有运行时类或方法。`box` 定义模块，`wide` 定义共享 Context 和输出路径，`eventbox` 定义底部打断时序。`flow` 表示读取或顺序消费；`write` 表示结果与文本写入；`control` 表示橙色话轮决策及优先控制；`thinking` 表示紫色虚线思考请求与结果；`feedback` 表示运行状态回传。`foreach` 为四个并列模块绘制 Context 读取箭头。

Nemotron 将在线转写写入 Context。XTurnix、Layer 0、Layer 1、Layer 2 分别读取当前可用信息，再把话轮动作、附和时机建议、表达输出、CoT 写回 Context。Layer 2 只发布 CoT 正文，不附带继续倾听、建议澄清或 start/keep/stop 标签；任务标识、版本、观察截止点和任务生命周期作为运行时元数据另记。CoT 同时对 XTurnix 和 Layer 1 可见，分别用于独立控制和表达。Layer 1 到 Layer 2 的直接虚线仅代表思考请求。

XTurnix 采用独立且比 Layer 1 micro-turn 更快的控制周期，具体周期尚未冻结。CoT 发布只更新 Context，不额外触发 XTurnix；各模块在下一次实际输入边界读取新信息。XTurnix 结合最新对话、已发布 CoT 和真实运行状态，独立判断全部话轮动作；决策写入 Context，由输出运行时及时消费。stop 不等待 Layer 1 推理完成，也不作为文本排入 FIFO。CoT 条件化控制仍需训练，不能视为原版权重已经具备。

Text FIFO 直接接收 Layer 0 路径的系统 backchannel 和 Layer 1 的表达文本；Context 不作为队列的文本来源。Layer 0 保留附和时机预测职责，具体附和措辞与编码本图不展开；两条提交路径仍共享唯一 TTS/播放器。每次连续输出分配 `output_id`，文本和音频块携带该标识与 `chunk_id`，FIFO 和播放器只接受当前有效输出。各模块对 Context 的读取和写回关系保留，Layer 1 的生成历史可见，但同一文本不重复注入模型输入。

## 打断执行与恢复

底部时序条对应同一个输出运行时的执行顺序：

1. 有效 stop 关闭旧 `output_id`，阻止旧文本继续入队。
2. 停止当前音频，取消旧标识下尚未播放的队列和音频缓冲，尽力取消在途生成与合成；迟到结果失去播放资格。
3. 播放器确认实际停播后，回传 Listen 与打断事件；生成、提交、取消和实际播放记录全部保留。
4. 后续有效 start 才允许使用新的 `output_id` 提交表达；旧队列不自动恢复。

Layer 1 在下一输入边界结合用户新输入和打断事件组织后续表达；活动 Layer 2 任务在自己的短推理边界消费新增观察，不因停播自动重启。图中回传运行状态与事件，不把精确播放位置或逐字已听文本作为 Layer 1 的常规输入。已听内容不可撤销；没有 Layer 3，Layer 2 不生成待播放正文。

## 产物与验证

[预览入口](../../figures/interclarify_method_preview.tex)生成[矢量 PDF](../../figures/interclarify_method_preview.pdf)和[高清 PNG](../../figures/interclarify_method_preview.png)。构建命令见[预览说明](interclarify_method_preview.md)。检查编译日志及渲染图中的文字、连线和裁切；此检查不属于模型或运行时测试。
