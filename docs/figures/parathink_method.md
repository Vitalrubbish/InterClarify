# 架构图绘制说明

更新：2026-10-29。对应[图源](../../figures/parathink_method.tex)，合同见[架构第2节](../research_design/architecture.md#2-模块与动作边界)。本版将XTurnix替换为SoulX-Duplug，并修正状态输入、持续音频及直接打断路径；图描述目标架构，不表示新链路已接入。

## 结构与绘图元素

TikZ源码没有运行时类或方法。`box`表示模块，`wide`表示Context和输出路径，`eventbox`表示打断时序；`flow`为读取和顺序消费，`write`为状态／文本写入，`control`为直接打断，`thinking`为思考请求与CoT发布，`feedback`为实际输出状态回传。

同一用户音频分别送Nemotron与SoulX-Duplug。在线转写先写Context；SoulX持续观察音频和对应转写，五类用户状态写入Context，供Layer 1在正常输入边界读取。普通正式回答在当前turn读取对应`user_complete`后生成，不因该状态另建回答调用。其他状态不转换为start或keep，不进入输出运行时。

Layer 2只发布内部CoT，不生成话轮建议或待播正文。CoT后续供SoulX与Layer 1在各自合法输入边界使用；对应适配和训练尚未实现，独立触发方式与输出是否扩展仍待设计。Layer 1到Layer 2的虚线只表示思考请求。

Layer 0路径的系统附和和Layer 1表达直接提交同一Text FIFO；附和正文由表达路径提供，Layer 0只预测时机。唯一输出运行时管理FIFO、TTS与播放器，检查`output_id`和`chunk_id`，并回传真实生命周期。生成、提交、取消和播放分别记录，Context不向FIFO提交文本。

## 打断与恢复

活动输出期间有效`user_nonidle`额外直接到达输出运行时，绕过FIFO，不等待Layer 1。底部四步依次为：关闭旧输出标识、停止并取消未播内容、确认关闭后发布Listen、Layer 1读取后续对应`user_complete`后生成新回答并登记新标识。准备阶段可取消尚未开播的输出，播放阶段须记录实际停播确认；迟到结果和旧队列不能恢复。

已听内容不可撤销，真实生成与播放历史保留；Layer 3定位待统一，本版不增加实现。预览产物与编译方法见[预览说明](parathink_method_preview.md)。
