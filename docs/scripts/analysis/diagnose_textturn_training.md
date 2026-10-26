# TextTurn训练诊断

`scripts/analysis/diagnose_textturn_training.py`对已有检查点和受限优化对照提供统一入口，作用是定位全keep退化，不替代正式训练和完整开发验收。协议见[诊断设计](../../dev/TextTurn/training_diagnostics.md)。文件使用函数组织，没有新增业务类。

`select_probe`固定来源哈希及动作邻域，保留所有所选来源的正例和有限keep对照；`action_loss`支持完整词表及状态合法动作CE；`evaluate_rows`保存逐例分数、margin及逐类混淆；`audit_gradients`检查真实16窗累积组；`compare_arm`复用现有加载、因果输入和阶段权重，记录每次更新范数并按原日程训练两轮。`main`校验冻结数据及输出目录，隔离检查和对照阶段，记录配置与模型身份。

所有模型计算只在远端GPU作业内执行，输入来自冻结train／dev而非外部测试。现役训练入口和配置保持不变，诊断adapter不得直接作为线上候选。
