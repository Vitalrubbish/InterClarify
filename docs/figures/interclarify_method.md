# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-23。

## 整体作用

按用户本轮确认的方案更新英文架构图：共享 Context 连接独立模块，移除独立 Arbiter，增加 Text FIFO，保留单一 TTS/播放器。图展示讨论确认的目标结构，不代表已完成运行时实现。本次只更新图及配套说明，不创建工作单，不展开尚在讨论的打断执行协议。

此前[研究架构文档](../research_design/architecture.md)仍描述单一仲裁器；本图依据本轮用户明确决定取消该独立模块。研究文档本次未修改，后续若启动工程实施，应先同步相关合同，不能将旧仲裁器描述与本图混用。

## 结构与绘图元素

文件为 TikZ 绘图源码，没有运行时类或方法。`box` 定义模块，`wide` 定义共享 Context 和输出路径。`flow` 表示读取或顺序消费；`write` 表示结果与文本写入；`control` 表示橙色话轮决策；`thinking` 表示紫色虚线思考请求与结果；`feedback` 表示运行状态回传。`foreach` 为四个并列模块绘制 Context 读取箭头。

Nemotron 将在线转写写入 Context。XTurnix、Layer 0、Layer 1、Layer 2 分别读取当前可用信息，再把话轮动作、附和时机建议、表达输出、增量分析结果写回 Context。Layer 2 结果因此同时对 XTurnix 和 Layer 1 可见，不再画成只直接返回 Layer 1。Layer 1 到 Layer 2 的直接虚线仅代表思考请求。

XTurnix 采用独立且比 Layer 1 micro-turn 更快的控制周期，具体周期尚未冻结。Layer 2 发布只更新 Context，不额外触发 XTurnix；各模块在下一次实际输入边界读取新信息。XTurnix 决策经 Context 驱动 Layer 1 表达，利用 thinking 条件的能力仍需适配，不能视为原版权重已经具备。

按用户最新修正，Text FIFO 直接接收 Layer 0 的系统 backchannel 和 Layer 1 的表达文本；Context 不作为队列的文本来源。Layer 0 保留附和时机预测职责，具体附和措辞与编码本图不展开；两条提交路径仍共享唯一 TTS/播放器。各模块对 Context 的读取和写回关系保留，Layer 1 的生成历史可见，但同一文本不重复注入模型输入。

图中只回传 Listen/Speak 等运行状态，不把精确播放位置或已听文本对齐作为 Layer 1 的常规输入。生成历史保留，单一 TTS/播放所有权保留；没有 Layer 3，Layer 2 不生成待播放正文。图不规定 stop 的队列清理时点、在途生成处理或控制执行顺序，这些打断细节依用户要求暂不展开。

## 产物与验证

[预览入口](../../figures/interclarify_method_preview.tex)生成[矢量 PDF](../../figures/interclarify_method_preview.pdf)和[高清 PNG](../../figures/interclarify_method_preview.png)。构建命令见[预览说明](interclarify_method_preview.md)。检查编译日志及渲染图中的文字、连线和裁切；此检查不属于模型或运行时测试。
