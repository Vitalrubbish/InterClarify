# 训练loss统计

`scripts/training/analyze_layer1_loss.py`为只读CPU分析入口，无业务类。`analyze`验证完整单epoch日志、游标、唯一序列及对话、监督token、各类目标数、普通/加权loss的恒等关系和有限梯度；核对checkpoint摘要及干净进程重载状态。

`aggregate`以实际有效监督token或目标权重和聚合CE，控制NLL按各类目标数聚合；正文与EOS作为日志可识别的剩余类别合并，不能单独解释为自然语言正文。`summarize`生成首/尾100步、全程、每50步曲线和五类目标贡献，记录预裁剪梯度及波动。允许只读旧040日志作描述性比较，但不得当作固定评测集对照。

输出`loss_analysis.json`及来源文件SHA256，逐步日志和大权重留远端。绘图只使用回收的分段统计，图中标注token加权与训练集口径，不推断验证集泛化或FDB表现。
