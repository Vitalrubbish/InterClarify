# 架构图预览入口说明

对应文件：[figures/interclarify_method_preview.tex](../../figures/interclarify_method_preview.tex)。更新：2026-10-22。预览展示完整项目架构，不标注实施阶段；Layer 0 结果与 Layer 1 待表达内容分别进入 Unified Arbiter，由 X2 user state 提供仲裁依据。Layer 0 的具体编码未定，不引入 backchannel cue 协议。

## 整体作用与结构

使用 `standalone` 文档类加载 TikZ 库，并通过 `input` 包含 [架构图源码](../../figures/interclarify_method.tex)，生成 [预览 PDF](../../figures/interclarify_method_preview.pdf)。本文件没有运行时类或方法，不包含模型调用或播放逻辑。

## 构建方式

在 `figures` 目录执行 `pdflatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/interclarify-figure-build interclarify_method_preview.tex`，事先创建输出目录，检查生成结果后将 PDF 同步到 `figures/interclarify_method_preview.pdf`。辅助文件留在临时目录，不纳入 Git。

图示职责和未决问题见 [架构图绘制说明](interclarify_method.md)。编译成功只证明图能够生成，不代表运行实现或模型能力通过验证。
