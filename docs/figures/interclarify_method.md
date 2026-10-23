# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-23。

## 整体作用

TikZ 图展示既有模块拓扑：X2-Turn 前端、Layer 0 系统附和时机预测、Layer 1 表达与调用、Layer 2 异步思考，以及唯一仲裁和播放。各模块使用普通边框，不标注实施先后、训练进度或当前步骤。实施安排见 [工程计划](../engineering_implementation.md)。模块职责以拆分后的[架构设计](../research_design/architecture.md#2-模块与动作边界)为准；现有图保留原主动澄清场景的说明，尚未展开边说边想的增量结果协议。

## 结构和职责

文件没有运行时类或方法。音频输入标注连接 frontend 中的 X2-Turn，shared 绘制当前可见共享上下文，module 绘制 Layer 0/1/2，output 绘制仲裁和播放；flow 表示输入/状态/内容，tool 的紫色虚线表示异步请求与结果，不表示实施进度。

X2-Turn 提供用户转写与原生状态，经共享上下文供后续模块消费，同时把 X2 user state 提供给唯一仲裁器。Layer 0 的结果和 Layer 1 的待表达内容分别直接进入仲裁器；仲裁器依据用户状态及实际播放状态选择、等待或停止输出。Layer 0 到仲裁器的箭头仅标为 Layer 0 result，不规定其具体字段、token 或 backchannel cue；不增加 Layer 0 到 Layer 1 的 cue 连线。Layer 1 请求 Layer 2，结果在正常输入边界注入并由 Layer 1 表达，不额外语义复核。

用户附和与系统附和方向不同。仲裁器协调 X2 状态、Layer 0 建议和 Layer 1 内容，所有发声经过单一 TTS/播放器。实际播放状态返回共享历史，已听内容不可撤销。当前研究中 Layer 0 只附和，Layer 2 提供澄清判断及回答分析，结果只注入上下文，不产生候选表达文本；语言表达由 Layer 1 生成，不设计 Layer 3。

## 构建

由 [预览入口](../../figures/interclarify_method_preview.tex)生成 [PDF](../../figures/interclarify_method_preview.pdf)。检查 Layer 0/1 各自进入仲裁器、X2 用户状态作为仲裁依据、表达/思考往返及唯一播放所有者；图中不出现实施阶段标签或具体未定的附和协议。辅助文件放 /tmp；编译图不等于运行实现验证。
