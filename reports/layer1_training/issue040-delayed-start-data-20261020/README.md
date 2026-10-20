# Issue 040：回答启动后移的数据交付

2026-10-20。用户本次授权实现数据后移，工作单元为 040a。源码提交 `a73569cdbc242029cb86e696e154a420da8d624f` 已推送，远端使用独立 detached worktree，不覆盖脏主仓库或 r5。

新配置显式采用 `generation.response_start_timing=next_no_voice`：普通末文字拍为 talking＋EOS，紧接的第一 no-voice 拍为 finish＋原回答首片段＋EOS；单片段插话当拍 interruption，下一拍直接 finish，不再增加 talking 拍。三视图共享计划。旧 manifest 未配置时仍复现历史时序。

远端路径为 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue040-delayed-start-data`。使用现役训练 conda，单 CPU、nice 10、线程 1、2GiB 虚拟地址空间、2GiB 单文件、10GiB 数据目录、至少 5GiB 空闲盘，无 GPU、并发 1；构建/审计/清点分别限时 1800/900/300 秒。执行前 `vc list` 无任务，空闲盘约 597GiB。启动后一次采样 RSS 为 153492KiB，此值不是峰值。

本地与远端各 32 项数据管线测试通过。本地训练模块 6 项通过、3 项张量测试按原策略跳过；未以本地检查代替远端模型训练。审查导出另有 3 项本地测试通过。构建、审计及序列清点均退出 0，配置冻结至完成约 662 秒，目录文件合计 979,069,697 字节（约 934MiB）。

本次只交付数据变更。未启动第三轮训练或 FDB 重测，未继承 r5 的人审豁免；新数据人审保持 pending，`training_allowed=false`。2048 序列清点和步数预估仅供后续实验冻结，不替代训练器放行索引。Issue 040 的 GPU 预算、正式配置、候选恢复和质量验收仍需后续完成。

机器审计见 [audit.json](audit.json)，train 清点见 [summary.json](summary.json)，远端测试原件见 [remote_tests.txt](remote_tests.txt)。相同 r5 的 1,000/200/300 对话及全部来源身份不变；选中对话 SHA256 仍为 `98fe4d085a8258566f3e08eeee119f324b5708eb68b4a31f5f4de2d82a75f401`。

| 检查 | 结果 |
| --- | --- |
| 全部回答启动 | 5,744 次，全部在第一 no-voice 拍 |
| train 回答启动 | 3,828 次 no-voice/finish；文字拍 finish 为 0 |
| train 末文字等待 | 3,828 次 talking，无回答正文 |
| train 随机句内暂停 | 12,826 拍，仍 talking |
| 原正文、用户跨度、随机事件 | 与冻结 r5 逐条一致；新增 5,744 个等待事件 |
| train 每条件 2048 序列 | 2,469（原 2,428） |
| train 每条件有效监督 token | 1,201,531（增加 7,656） |
| 有效 batch 2 的单 epoch 步数预估 | 1,235；10% warmup 向上取整 124 |
| 三视图目标和 mask | 完整审计通过，无重复监督 |

新清单 SHA256 为 `86c0faca1e1a12d3c7cf1fa0144e53a6a83166a8454ad48d986b24d40a97761d`。完整序列 ID 清点留在远端 `sequence_inventory.json`，SHA256 为 `7e30536002d4cd3a76b7ac57a6bc8ce777f5115e24af0409593179181caecbea`。本地保留其摘要，未复制近 1GiB 数据。原 r5 未修改。

每个普通回答相对该用户末文字增加一拍，即合成节拍 600ms；单片段插话原本已独立 finish，新模式仍下一拍直接启动，该分支由回归用例覆盖，本次实际数据未出现。此处仅报告合成监督时序，不推断训练后真实时延或接话质量。训练内“前缀看似完整但仍有补充”的语义负例人工覆盖核查仍留在 040；本次仅确认所有原随机暂停均保留。
