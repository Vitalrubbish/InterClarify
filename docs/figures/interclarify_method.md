# 架构图绘制说明

对应文件：[figures/interclarify_method.tex](../../figures/interclarify_method.tex)。更新：2026-10-21。

## 整体作用

以 TikZ 泳道图展示持续语音输入、双工表达、异步思考和统一输出路径。该图是讨论中的架构示意，新增思考调用尚未接入运行实现；研究范围以 [research_idea.md](../research_idea.md) 为准。

## 绘图结构

文件没有运行时类或方法。`lane` 绘制连续泳道，`cell` 绘制示例事件，`next` 表示输出路径，`reasoning` 表示思考请求与工具结果回写。五列沿用原图的示例位置，不代表一次问答能在固定数量的 micro-turn 内完成。

本次确认的关系为：Layer 1 发起异步请求，Layer 2 思考工具执行，结果回写 Layer 1；Layer 1 继续承担表达，仲裁器协调输出，TTS 保持单一播放所有权。Layer 2 没有直达输出选择或播放的路径。

## 待讨论细节

工具返回内容格式、回写时点、有效性检查、Layer 1 执行约束、调用与双工动作的关系仍未敲定。Alex 场景、示例回答、Layer 0 附和及时间轴沿用原图，不代表确认其研究合理性或开启附和能力；Layer 3 未展开，仍仅允许对未提交片段提交版本化修订补丁。

## 预览与验证

由 [预览入口](../../figures/interclarify_method_preview.tex) 包含本文件并生成 PDF。修改后编译预览、检查 LaTeX 报错与版面，并核对请求和返回箭头方向，确保没有 Layer 2 覆盖 Layer 1 文本的旧路径。
