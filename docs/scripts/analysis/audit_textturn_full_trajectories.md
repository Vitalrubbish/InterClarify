# 完整轨迹及权重核查

`scripts/analysis/audit_textturn_full_trajectories.py`的`audit`核查新冻结资产与旧基线的摘要、完整事件逐字节一致性、来源隔离及dev200来源保留。逐行解压数据，验证每条轨迹0起连续编号、窗口数等于真实控制请求数、正损失权重、合法动作ID、完整prompt实际token编码、finish输入掩码及keep组总权重。

pilot必须包含完整来源组，所有行必须与train对应行一致；训练≤10000窗，pilot≤2000窗，陈述／疑问四种对照完整。91459的question:normal必须70/70窗保留。audit.json绑定manifest及训练配置SHA256，供远端提交前检查，不能只凭文件存在放行。

CPU、单线程、Hugging Face离线tokenizer，无模型加载。入口：`python scripts/analysis/audit_textturn_full_trajectories.py --data artifacts/textturn/tt-010-fulltraj-r1 --base artifacts/textturn/tt-010-duplex160-r2`。失败保留冻结数据，不改标签或删除异常窗口。
