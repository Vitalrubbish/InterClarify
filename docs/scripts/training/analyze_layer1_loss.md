# Layer1训练损失分析

`scripts/training/analyze_layer1_loss.py`只分析已回收的训练记录和train监督频数，不加载模型、不改变训练目标、不计算内容质量或FDB分数。输入为032记录的完整T1逐步loss、梯度、学习率、有效token及训练事件频数，输出目录拒绝覆盖。

无业务类。`aggregate`同时计算每步loss算术均值和按有效监督token加权均值，避免把大小不同的累积批次当作相同token数；`analyze`检查步数连续、有限loss/梯度、监督总数与最终summary一致，生成100步窗口及首尾100步比较。训练样本顺序固定随机化，窗口间不是同一批输入；变化不能当作配对性能提升或过拟合证据。

`class_mass`分别统计正文、EOS和五类控制token的监督占比，并计算采用论文1/10/5/2/1权重时的名义目标权重占比。该占比不等同实际loss或梯度贡献；当前没有按类别模型NLL、召回率及混淆矩阵，程序不会伪造这些指标。

`plot`生成独立PNG/PDF图：原始loss、50步token加权滑动均值、学习率及控制监督数量。`main`保存summary.json、使用LF换行的steps.csv和图文件。图中文字、代码注释和文件名使用英文，研究解释由中文报告给出。

本地使用已有conda `ml-hw1`中的NumPy/Matplotlib运行；远端数据提取仅用独立training conda和stdlib，单CPU、2GiB虚拟地址硬限，不占GPU。输出只表示训练稳定性和目标分布分析，不能据此选择中间checkpoint或宣称真实控制能力提高。
