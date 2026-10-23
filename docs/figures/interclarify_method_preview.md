# 架构图预览入口说明

对应文件：[figures/interclarify_method_preview.tex](../../figures/interclarify_method_preview.tex)。更新：2026-10-23。

## 整体作用与结构

使用 `standalone` 文档类加载 TikZ 库，通过 `input` 包含[架构图源码](../../figures/interclarify_method.tex)。外围保留 16pt 留白，图内使用较大英文文字。文件没有运行时类或方法，不包含模型调用或播放逻辑。模块职责和连线解释见[图示说明](interclarify_method.md)。

本版展示各模块对共享 Context 的读取和写回、独立高频 XTurnix 周期，以及 Layer 0/1 直接提交至 Text FIFO 的输出路径。橙色优先控制线绕过 FIFO，进入兼有唯一仲裁执行点与 TTS/播放器的输出运行时；Context 不向 FIFO 提交文本。底部时序条展示旧 `output_id` 关闭、停播与取消、确认 Listen，以及有效 start 后使用新标识输出。运行时向 Context 回传真实状态和打断事件。

Layer 2 仅将 CoT 发布至 Context，不提供话轮建议；XTurnix 负责全部话轮决策，Layer 1 利用同一 CoT 组织表达。图中 CoT 写回线与控制动作线分开，CoT 条件化控制标注为仍需训练。

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

辅助文件保留在临时目录，不纳入 Git。检查编译日志无文字溢出或缺字，并打开 PNG 核对模块、标签、箭头和留白，重点确认控制线绕过 FIFO、停止确认先于 Listen、新输出等待有效 start。对照[架构文档](../research_design/architecture.md)检查模块职责和打断合同。编译通过只证明图可生成，不代表模型能力或工程接入已通过验证。本流程不运行 Python，无需新增 Python 环境。
