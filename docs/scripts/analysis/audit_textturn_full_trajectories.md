# 完整轨迹及权重核查

`scripts/analysis/audit_textturn_full_trajectories.py`的`audit`核查新冻结资产与旧基线的摘要、完整事件逐字节一致性、来源隔离及dev200来源保留。逐行解压数据，验证每条轨迹0起连续编号、窗口数等于真实控制请求数、正损失权重、合法动作ID、完整prompt实际token编码、finish输入掩码及keep组总权重。

pilot必须包含完整来源组，所有行必须与train对应行一致；训练≤10000窗，pilot≤2000窗，陈述／疑问四种对照完整。91459的question:normal必须70/70窗保留。audit.json绑定manifest及训练配置SHA256，供远端提交前检查，不能只凭文件存在放行。

CPU、单线程、Hugging Face离线tokenizer，无模型加载。入口：`python scripts/analysis/audit_textturn_full_trajectories.py --data artifacts/textturn/tt-010-fulltraj-r1 --base artifacts/textturn/tt-010-duplex160-r2`。失败保留冻结数据，不改标签或删除异常窗口。

2026-10-26损失平衡适配：冻结数据继续按原manifest文件摘要及基础权重逐项审核，loss_policy必须相符。原loss_helper源码摘要作为生成时来源记录，当前helper增加训练阶段功能后允许摘要不同，并同时记录新旧摘要；用逐行权重公式、组质量及原始资产摘要验证实际冻结内容，不能因合法训练实现升级强制重写数据。keep每行还须等于所在组的基础权重，不仅检查组总和。

按当前loss_balance对pilot／train独立计算有效权重摘要，核对三类质量符合配置份额，写入audit.json并绑定当前训练配置摘要。这是CPU完整性审核，不加载GPU模型，不代表质量通过。
