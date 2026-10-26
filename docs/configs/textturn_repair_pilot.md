# TextTurn有限pilot配置

`textturn_repair_pilot.json`冻结固定Qwen revision、LoRA16／32、AdamW学习率1e-4、最大输入2048、clip1和组内三类平均损失。旧pilot两轮、新pilot五轮，从相同基模初始化；窗口预算10000，不自动full或外部测试。质量线为正例80%、误动作15%、至少30个机会、控制P95≤500ms；显存停止线22GiB、资产10GiB、报告2GiB，有限遍历自然结束，不设应用层总训练时限。
