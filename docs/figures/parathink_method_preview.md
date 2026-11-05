# 架构图预览入口说明

更新：2026-11-06。对应[预览入口](../../figures/parathink_method_preview.tex)，文件用standalone加载TikZ和[图源](../../figures/parathink_method.tex)，没有运行时类或方法。结构见[图示说明](parathink_method.md)。

预览按用户要求精简为模块名称、步骤名称与连接标签，删除各框标题下方及图旁的叙述说明，并同步收紧布局。详细行为继续参见图示说明和架构设计。

[PDF](../../figures/parathink_method_preview.pdf)和[PNG](../../figures/parathink_method_preview.png)已同步原生SoulX内部SenseVoice、独立X2、160ms联合写Context及下游共同快照消费，Layer 1统一负责附和时机与措辞及正式表达，Layer 2发布CoT。普通回答读取已提交有效complete和当前正文，下游接入仍待后续工作单。

## 构建与检查

在项目根目录逐条运行，辅助文件留在临时目录：

```bash
mkdir -p /tmp/parathink-figure-build
cd figures
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/parathink-figure-build parathink_method_preview.tex
cp /tmp/parathink-figure-build/parathink_method_preview.pdf parathink_method_preview.pdf
pdftoppm -png -singlefile -scale-to 3200 parathink_method_preview.pdf parathink_method_preview
```

检查日志无文字溢出或缺字，并打开PNG核对裁切、标题和箭头，确认各框没有标题下方的说明段落：两路只联合写Context，外部X2不进入状态KV，下方并列Layer 1和Layer 2，nonidle从已提交Context读到后才进入唯一输出执行点，未来CoT反馈用点线。编译通过只验证图可生成，不证明模型或播放链路验收；该流程不运行Python。
