# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-23。

## 整体作用

根据用户要求重新绘制英文架构图，替换旧 X2-Turn 标注，放大文字并拉开模块与连线间距。图展示当前研究设计的职责关系，不代表模块已完成接入。研究合同以[架构设计](../research_design/architecture.md)为准，本次不修改研究范围、不创建工作单。

## 结构与绘图元素

文件为 TikZ 绘图源码，没有运行时类或方法。`box` 定义模块，`wide` 定义共享上下文与执行路径；`flow` 为普通数据流，`control` 为橙色控制动作，`thinking` 为紫色虚线异步请求及结果，`feedback` 为青色实际播放反馈。`foreach` 为四个并列模块绘制上下文输入。

Nemotron 只提供在线转写。XTurnix 与 Layer 0/1/2 并列：分别负责话轮策略、系统附和时机、语言表达和异步分析。XTurnix 的 Listen 下 keep/start 与 Speak 下 keep/stop 输入统一仲裁器；Layer 0 的时机建议和 Layer 1 待表达内容也输入同一仲裁器。

Layer 1 请求 Layer 2，分析结果在下一个正常输入边界注入 Layer 1 上下文；图中的返回箭头表示上下文注入，不表示直接生成或替换待播放文本。Layer 2 在听和说期间均可分析，但不拥有播放执行权。thinking 条件化话轮控制仍为后续适配事项，图底部单独说明，不绘制成已具备的能力。

所有可听输出经过唯一仲裁器和 TTS/播放路径。实际播放状态与已播历史反馈共享上下文；Listen/Speak 由真实运行状态维护。没有 Layer 3，已听内容不可撤销，Layer 2 不修改播放队列。

## 产物与验证

[预览入口](../../figures/interclarify_method_preview.tex)生成[矢量 PDF](../../figures/interclarify_method_preview.pdf)和[高清 PNG](../../figures/interclarify_method_preview.png)。构建命令见[预览说明](interclarify_method_preview.md)。通过编译日志和渲染图检查文字、连线及裁切；此检查不属于模型或运行时测试。
