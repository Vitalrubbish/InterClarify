# Issue 004：修复后正式数据交付（r4）

2026-10-19。远端 `issue004-build-r3` 生成目录及仓库中的旧审计副本已按用户要求删除。当前唯一待人工签署的正式产物为 `issue004-build-r4`，位于远端 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue004-build-r4/`。r3 的缺陷与复核摘要仍记录在 `docs/duplex_data_alignment_audit.md`，旧产物不参与训练或签署。

r4 使用修复源码 `70d57b6c0067d3af0e7cf175ed347513923546b2`，在 `d6-hpc-debuggpu-001` 的独立 conda 环境以单 CPU、nice 10、2GiB 虚拟内存上限及3600秒外层时限执行。构建、全量审计、审查材料导出均成功，`exit_code.txt=0`。用户已确定的“前32条签署即可关闭004”政策经单独重审，`policy_reaudit_exit_code.txt=0`；机器审计通过、人工签署为空、`training_allowed=false`。

抽取6000条原始 UltraChat 对话，过滤后5730候选，选出 train/dev/test 为1000/200/300；三臂共5394个监督序列、281260个基础微轮。T3 训练视图500/500。标点独占用户片段合并2355次，合并后超过7个基础token的用户片段336个；这些是已登记的论文参数例外。全量机器审计要求每个有来源跨度的用户微轮在原样与去句读视图均非空。前32条材料共6222事件，独立核对空去句读用户片段为0。

[32条逐条人工审计](review_32/README.md)为用户入口；[机器审计及来源摘要](completed/README.md)供复核。当前等待真实用户签署，不自动关闭004，也不放行005/007训练门禁。
