# TextTurn训练机制诊断与方案

2026-10-26按用户要求在TT-010内测试并确定新训练方案，不新增issue。诊断设计在执行前已记录于[协议](../../../docs/dev/TextTurn/training_diagnostics.md)，正式训练代码、冻结数据和TT-011外部回归保持原状。

## 执行记录

源码`490169c`已推送并由服务器fetch，独立worktree为`~/parathink-textturn/source/tt010-diagnostics-r1`。本地conda共67项TextTurn测试通过，其中新增3项诊断边界测试；shell语法及diff检查通过。

只读检查作业`job-179299289638041093984-xuan-zhang`于13:34:56提交并确认Running，run为`tt010-diagnostic-inspect-r1`。检查初始化基模和r2的best／final：pilot全量1894窗；开发探针20来源／1533窗，包含80个start与40个stop。pilot边界探针315窗，供后续优化对照使用。固定来源和窗口ID进入run manifest，不使用外部测试。

资源为单RTX4090／8CPU／32GiB RAM、单作业，诊断7200秒、外层7300秒兜底，显存22GiB、项目资产10GiB／报告2GiB及30GiB空盘停止线。原始日志位于远端`~/parathink-textturn/submit_logs/tt010-diagnostic-inspect-r1.diagnostic.log`，run保存逐例输出和汇总。当前仅代表已启动，结果待实际完成后补充。

## 只读复评结果

inspect已正常结束，退出码0。best和final在完整pilot1894窗、固定dev探针1533窗上均只选keep，训练正例start0/16、stop0/8；这次已直接确认训练样本未学会，并非仅开发来源泛化不足。作为对照，同样动作初始化的基模在pilot上start2/16、stop7/8，在dev探针上start4/80、stop20/40；训练确实消除了原有动作响应。

final的pilot平均正确动作margin：keep+6.926、start−5.250、stop−3.516。full CE与合法动作CE在这些正例上已接近，说明塌缩权重主要偏向keep，而非普通词竞争。best的start／stop平均margin分别−6.461／−6.781。

在final上抽查8个真实累积组：4个仅keep组范数0.109／0.529／0.873／1.020，2个start组599.715／600.150，2个stop组1211.830／1239.310。按norm=1计算，start梯度仅保留约0.167%、stop约0.081%—0.083%，keep大多不裁剪。动作输出行均收到非零梯度。该测量支持裁剪会强烈改变跨更新组尺度，但描述的是final当前梯度，不能冒充历史梯度。

原始summary已取回本地`artifacts/analysis/textturn/training-diagnostics-20261026/inspect-summary.json`，SHA256为`34801c2d8c65af0730e3f3debd161b71f97bf4d8c3cdd71cf39ac7f463a0a608`。优化对照已在inspect结束、无活动作业后提交，job为`job-179299343091965523098-xuan-zhang`，run为`tt010-diagnostic-compare-r1`，三臂仍按冻结协议串行，结果待完成。
