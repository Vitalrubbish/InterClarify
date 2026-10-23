# 架构图预览入口说明

对应文件：[figures/interclarify_method_preview.tex](../../figures/interclarify_method_preview.tex)。更新：2026-10-23。

## 整体作用与结构

使用 `standalone` 文档类加载 TikZ 库，通过 `input` 包含[架构图源码](../../figures/interclarify_method.tex)。外围保留 16pt 留白，图内使用较大英文文字。文件没有运行时类或方法，不包含模型调用或播放逻辑。模块职责和连线解释见[图示说明](interclarify_method.md)。

本版展示各模块对共享 Context 的读取和写回、独立高频 XTurnix 周期，以及 Layer 0/1 直接提交至 Text FIFO、再到单一播放器的输出路径；Context 不向 FIFO 提交文本。移除旧版独立 Arbiter，不展示打断处理时序。

产物为可任意放大的[矢量 PDF](../../figures/interclarify_method_preview.pdf)，以及便于直接查看的[高清 PNG](../../figures/interclarify_method_preview.png)。两者来自同一次构建。

## 构建方式

在项目根目录逐条运行：

```bash
mkdir -p /tmp/interclarify-figure-build
cd figures
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/interclarify-figure-build interclarify_method_preview.tex
cp /tmp/interclarify-figure-build/interclarify_method_preview.pdf interclarify_method_preview.pdf
pdftoppm -png -singlefile -scale-to 3200 interclarify_method_preview.pdf interclarify_method_preview
```

辅助文件保留在临时目录，不纳入 Git。检查编译日志无文字溢出或缺字，并打开 PNG 核对模块、标签、箭头和留白。编译通过只证明图可生成，不代表模型能力或工程接入已通过验证。本流程不运行 Python，无需新增 Python 环境。
