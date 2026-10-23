# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-23。

## 整体作用

TikZ 图保留此前 X2-Turn 前端与主动澄清场景的模块标注，以及 Layer 0/1/2、唯一仲裁和播放。当前方案已改为 Nemotron ASR＋XTurnix，旧图尚未同步，不能作为当前组件清单；也未展开边说边想的增量分析协议。各模块使用普通边框，不标注实施先后、训练进度或当前步骤。实施安排见[工程计划](../engineering_implementation.md)，当前模块职责以[架构设计](../research_design/architecture.md#2-模块与动作边界)为准。

## 结构和职责

文件没有运行时类或方法。音频输入标注连接 frontend 中的 X2-Turn，shared 绘制当前可见共享上下文，module 绘制 Layer 0/1/2，output 绘制仲裁和播放；flow 表示输入/状态/内容，tool 的紫色虚线表示异步请求与结果，不表示实施进度。

图中的前端转写/状态连线属于旧方案。当前应由 Nemotron 提供真实转写，XTurnix 给出状态条件下的 keep/start/stop 决策，经唯一仲裁器执行；其他模块继续消费当前可见上下文。Layer 0 结果和 Layer 1 待表达内容仍分别进入同一仲裁器；Layer 0 抽象输出的具体字段和编码未定，不新增 backchannel cue。Layer 1 请求 Layer 2，thinking 结果在正常输入边界注入，由 Layer 1 继续表达，不增加独立任务语义复核层。

用户附和与系统附和方向不同，XTurnix 的 Speak/keep 不直接充当系统附和标签。仲裁器协调控制决策、Layer 0 建议和 Layer 1 内容，所有发声经过单一 TTS/播放器。实际播放状态返回共享历史，已听内容不可撤销。Layer 0 只附和，Layer 2 提供澄清判断及回答分析，结果只注入上下文，不产生候选表达文本；语言表达由 Layer 1 生成，不设计 Layer 3。

## 构建

由[预览入口](../../figures/interclarify_method_preview.tex)生成[PDF](../../figures/interclarify_method_preview.pdf)。后续更新图时检查 Nemotron/XTurnix 拆分、Layer 0/1 各自进入同一仲裁器、表达/思考往返及唯一播放所有者；不增加具体未定的附和协议。辅助文件放 /tmp；本次未修改绘图源码或重新构建，编译图也不等于运行实现验证。
