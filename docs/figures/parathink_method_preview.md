# 架构图预览入口说明

更新：2026-10-29。对应[预览入口](../../figures/parathink_method_preview.tex)。文件使用`standalone`加载TikZ及[图源](../../figures/parathink_method.tex)，保留16pt留白，没有运行时类或方法。模块、连线和打断时序见[图示说明](parathink_method.md)。

同次构建生成[矢量PDF](../../figures/parathink_method_preview.pdf)和[高清PNG](../../figures/parathink_method_preview.png)，均展示SoulX-Duplug状态进入Layer 1、有效用户打断直接停止输出，以及后续CoT条件化目标。

## 构建与检查

在项目根目录逐条运行：

```bash
mkdir -p /tmp/parathink-figure-build
cd figures
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/parathink-figure-build parathink_method_preview.tex
cp /tmp/parathink-figure-build/parathink_method_preview.pdf parathink_method_preview.pdf
pdftoppm -png -singlefile -scale-to 3200 parathink_method_preview.pdf parathink_method_preview
```

辅助文件留在临时目录。检查日志无文字溢出或缺字，并打开PNG核对名称、连线和裁切：音频同时到ASR与SoulX，状态经Context进入Layer 1，仅有效用户打断绕过FIFO；关闭确认先于Listen，新回答遵循`user_complete`可见边界。图文合同以[架构设计](../research_design/architecture.md)为准。编译仅验证图可生成，不代表模型或运行时验收；本流程不运行Python。
