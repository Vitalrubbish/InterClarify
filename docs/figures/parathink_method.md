# 架构图绘制说明

更新：2026-10-29。对应[图源](../../figures/parathink_method.tex)，合同见[架构第 2 节](../research_design/architecture.md#2-模块与动作边界)。按用户确认，本版将 SoulX-Duplug 与 SenseVoiceSmall 收入顶部语音前端，Context 下方只并列展示 Layer 0–Layer 2。首版先使用官方配套 ASR 打通链路，后续再评估 Nemotron，以减少首轮适配工作。图描述目标架构，不表示新链路已接入。

## 结构与绘图元素

TikZ 源码没有运行时类或方法。`frontend` 表示语音前端边界，`box` 表示内部组件与下游模块，`wide` 表示 Context 和输出路径，`eventbox` 表示打断时序。`flow` 为输入、读取和顺序消费，`write` 为状态／文本写入，`control` 为直接打断，`thinking` 为思考请求与 CoT 发布，`future` 为尚未实现的 CoT 反馈，`feedback` 为实际输出状态回传。

用户音频进入语音前端，其中 Online ASR 首版使用 SenseVoiceSmall，后续评估 Nemotron；SoulX 组件包含音频编码和用户状态预测。内部 ASR 到 SoulX 的连线表示同一来源转写参与状态判断。前端向 Context 分别发布版本化在线转写与五类用户状态，文字更新不等待 `user_complete` 或状态预测完成。在线转写允许修订，不再标为单调追加前缀，也不把窗口识别称为原生流式 ASR。中间文本到话轮快照的整理仍待实现与验证。

Context 下方三列分别为 Layer 0 系统附和时机、Layer 1 表达与思考请求、Layer 2 异步思考。前端位于输入侧，但持续音频观察、表达与思考可并发执行，图中的前后关系不表示整轮串行等待。Layer 0 系统附和与前端识别用户附和是不同职责。普通正式回答在当前 turn 读取对应 `user_complete` 后生成，不因该状态另建回答调用；其他状态不转换为 start 或 keep，不进入输出运行时。

Layer 2 只发布内部 CoT，不生成话轮建议或待播正文。Context 至前端的点线标明未来 CoT 条件化反馈，供 SoulX 在合法输入边界使用；对应适配和训练尚未实现，独立触发方式与输出是否扩展仍待设计。Layer 1 读取同一 Context 中已发布的分析。Layer 1 到 Layer 2 的虚线只表示思考请求。

Layer 0路径的系统附和和Layer 1表达直接提交同一Text FIFO；附和正文由表达路径提供，Layer 0只预测时机。唯一输出运行时管理FIFO、TTS与播放器，检查`output_id`和`chunk_id`，并回传真实生命周期。生成、提交、取消和播放分别记录，Context不向FIFO提交文本。

## 打断与恢复

活动输出期间有效`user_nonidle`额外直接到达输出运行时，绕过FIFO，不等待Layer 1。底部四步依次为：关闭旧输出标识、停止并取消未播内容、确认关闭后发布Listen、Layer 1读取后续对应`user_complete`后生成新回答并登记新标识。准备阶段可取消尚未开播的输出，播放阶段须记录实际停播确认；迟到结果和旧队列不能恢复。

已听内容不可撤销，真实生成与播放历史保留；Layer 3定位待统一，本版不增加实现。预览产物与编译方法见[预览说明](parathink_method_preview.md)。
