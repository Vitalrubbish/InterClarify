# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-22。

## 整体作用

TikZ 图展示总架构：X2-Turn 前端、Layer 0 系统附和时机预测、Layer 1 表达与调用、Layer 2 异步思考，以及唯一仲裁和播放。当前先接入 X2-Turn；Layer 0 以虚线表示后续保留，当前不实现或训练。图替换旧“Layer 0 话轮分类”分工，对应 [研究方案第 7 节](../research_design.md#7-系统工程架构)，不表示已经部署。

## 结构和职责

文件没有运行时类或方法。input绘制音频输入，frontend绘制X2-Turn，shared绘制当前可见共享上下文，module绘制Layer 0/1/2，output绘制仲裁和播放；flow表示输入/状态/内容，tool表示请求与结果。

X2-Turn提供用户转写与原生状态，经共享上下文供后续模块消费，同时把用户状态提供给唯一仲裁器。Layer 0只预测系统附和时机，输出建议进入仲裁；它不重新输出用户话轮状态，也不生成或播放正文。Layer 1提供回答/附和/澄清正文，并请求Layer 2；结果在正常输入边界注入，不额外语义复核。

用户附和与系统附和方向不同。仲裁器协调X2状态、Layer 0建议和Layer 1内容，所有发声经过单一TTS/播放器。实际播放状态返回共享历史，已听内容不可撤销。Layer 0只附和，Layer 2判断主动澄清，不增设修订层。

## 构建

由 [预览入口](../../figures/interclarify_method_preview.tex)生成 [PDF](../../figures/interclarify_method_preview.pdf)。检查X2用户状态路径与Layer 0系统附和路径、表达/思考往返及唯一播放所有者。辅助文件放/tmp；编译图不等于运行实现验证。
