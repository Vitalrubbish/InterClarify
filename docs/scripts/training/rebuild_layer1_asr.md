# 固定来源重建ASR数据

`scripts/training/rebuild_layer1_asr.py`从冻结040a数据重建四视图，无业务类。`rebuild`核对原manifest和selected摘要，逐条验证旧产物并复现原事件计划，确认新增ASR字段之外的事件、正文和随机计划不变，再编码原样、去句读、混合与ASR视图。复制原来源/切分与外部排除信息，不重新抽样或借用dev/test。

输出新manifest、原始对话、视图分配、逐对话产物及人审pending模板，拒绝覆盖。构建后复用全量审计，再用`ProbeDataset`生成ASR训练器实际索引；统计与完整原文分别留报告和远端。
