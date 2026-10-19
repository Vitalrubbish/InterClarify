# Issue 004：r5正式数据交付

2026-10-19。Issue 004、018及021已完成归档。最终run_id为`issue004-build-r5`，源码`7cda3b1`；[机器审计原件](completed/audit.json)确认`machine_passed=true`、`parent_issue_complete=true`，构建[退出码](completed/exit_code.txt)为0。用户明确要求r5不再人工审查并直接关闭004，记录`human_review_waived=true`；没有伪造逐条签署，也不生成新人工审查材料。

| 项目 | r5结果 |
| --- | --- |
| 有限读取／过滤后候选 | 6000／5278 |
| train／dev／内部文本test对话 | 1000／200／300 |
| 三臂监督序列总数 | 5271 |
| 基础micro-turn总数 | 270730 |
| 每臂有效监督token总数 | 1780660 |
| T3训练保留句读／去句读 | 500／500 |
| 原文及规范化后跨集合近重复 | 均为0 |
| 完整用户轮数值替换 | 954次，11个类别 |
| 因不支持或歧义数值上下文排除 | 468条 |
| 标点独占片段合并／超过7基础token片段 | 2177／286 |
| 有来源用户片段去句读后为空 | 0，机器门禁 |
| 用户规范化文本残留数字 | 0，机器门禁 |

用户数值先转换成确定性英文读法，再按token分拍及构造三视图；大小写和撇号保留，词内增量允许，assistant文本不变。`plan.user_turns`保留原文、规范化文本与双向跨度。数字表面形式是基于当前ASR观测的合成近似，不宣称精确复现真实ASR到达时钟或所有发音。歧义日期及暂不支持的代码/公式等按预登记规则过滤，不按模型效果挑选样本。最小替换样例见[numeric_examples.json](completed/numeric_examples.json)。

本地、远端独立conda各34项相关测试通过。正式运行在`d6-hpc-debuggpu-001`：单CPU、nice10、2GiB虚拟地址空间、单文件2GiB、目录10GiB、可用磁盘保留5GiB，外层3600秒；不使用GPU。r5-attempt1在候选分组早期主动取消，用于补齐大整数/负金额/年月等边界，不计为正式产物；正式r5从干净目录完整重建。有效配置、构建日志、依赖清单及来源摘要在[completed](completed/README.md)。

远端生成目录：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue004-build-r5/`。r4生成目录约631MiB及仓库旧审计副本已删除。原始UltraChat、发布tokenizer与模型均保留。

清单SHA256：`4876c0940379259756c4709fe603cf7a6c9d77bc2248a1a5d1c0abdcad44c5115`。

004数据门禁通过；005零更新/恢复及007开训前准备仍待完成，`training_allowed=false`，尚未启动训练。
