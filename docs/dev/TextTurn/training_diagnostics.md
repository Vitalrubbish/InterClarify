# 全keep退化的受限诊断

2026-10-26，用户授权测试后确定新训练方案，纳入现有TT-010，不新增issue。本协议在代码和远端执行前冻结。目标是区分训练正例未学会、裁剪影响及开发泛化问题，不自动启动正式训练或外部回归。

## 输入与比较

固定r2使用的Qwen3-0.6B、完整轨迹数据、token注册和seed。首先分别加载初始化基模、r2的best和final，完整评估pilot1894窗；另从dev按来源ID固定哈希选择20来源，仅保留所有动作锚点、同轨迹前后各两窗及各状态／类别最多两条keep作开发探针。选择不读取预测结果，不把缺失窗口的探针分数当作完整机会质量。记录逐类混淆、完整词表／合法动作CE、正确动作对另一个合法动作的margin。

在final上，按真实seed顺序检查4个仅keep累积组、2个含start组、2个含stop组的梯度，原样保留每组最多16窗，记录全参数范数及动作token行范数；该测量描述当前权重，不能还原历史训练梯度。

随后各臂从同一初始化基模重新开始，每臂完整pilot两轮：

| 臂 | CE归一化范围 | 梯度裁剪 | 用途 |
| --- | --- | --- | --- |
| full_clip1 | 完整词表 | norm=1 | 仪器化复现原行为 |
| full_no_clip | 完整词表 | 不裁剪，非有限立即停止 | 单独检查裁剪因素 |
| legal_clip1 | 当前状态两个合法动作 | norm=1 | 单独检查目标与决策空间差异 |

LoRA、新token行、学习率1e-4、warmup5%、余弦日程、累积16窗、AdamW与weight decay0.01不变。全部1894窗每轮各使用一次，轨迹内顺序不变，三类有效系数各1/3，不复制正例、不删除keep。合法动作CE只改变softmax范围，仍通过同一动作token输出，不增加分类器或第四个动作。

各轮评估固定pilot边界探针和固定dev探针，记录逐类预测、loss和每次参数更新的裁剪前范数。保留每臂final供后续核查。方案比较同时看start／stop召回和Listen误start／Speak误stop，不能仅凭总loss或更频繁动作选方案。若三臂均未学会，应据实补充诊断，不预先选定方案；任何后续对照先记录目的和条件。

## 资源与产物

模型作业全部远端conda和调度器执行，最多一个活动作业，1×24GiB GPU／8CPU／32GiB RAM，worker=0，显存停止线22GiB。每个诊断作业最多7200秒，新增诊断产物控制512MiB内；项目资产10GiB、报告2GiB、启动及运行空盘30GiB停止线保留。此处是诊断上限，不恢复正式训练已取消的时间上限。

只读检查与优化对照使用不同run目录，原r2模型、数据和日志不覆盖。配置、代码commit、数据manifest摘要、环境、分组和逐例输出可追溯。Git只保存简洁中文结果与最终方案，原始JSON／JSONL和adapter留在服务器及本地artifacts。

实现入口为`scripts/analysis/diagnose_textturn_training.py`，远端包装为`scripts/remote/run_textturn_diagnostics.sh`，参数见`configs/textturn_training_diagnostics.json`。先完成只读检查，再根据其结果执行对照；不恢复TT-011等待器。
