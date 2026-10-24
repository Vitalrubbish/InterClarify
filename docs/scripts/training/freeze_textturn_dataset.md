# TextTurn 正式数据冻结

对应 `scripts/training/freeze_textturn_dataset.py`，属于 TT-001。

`fetch_source` 流式下载固定 UltraChat train_0，检查完整大小及公开 LFS SHA256；不以 HTTP 前缀替代完整校验。`collect_exclusions` 从 Git 历史索引读取已用来源，连同检查批次排除。`select_sources` 仅选择满足保守完整表达及不完整前缀条件的源对话，记录跳过原因；全量来源与逐行位置可追溯。

`make_plan` 构造包含两次 start、正常播放完成、短附和、停顿和打断的连续轨迹，复用 `ControlTokenizer` 和 `compile_scenario`，保持 480ms、User 1—2 token、Assistant 8 token。规则标注依据及插入文本显式保存，不向模型暴露类别、计划或未来文字。`freeze` 在切分前去重，保留完整轨迹；训练分层抽取至多 10,000 窗、pilot 至多 2,000 窗，开发／测试保留全窗，并报告超长和未知。仅动作参与损失。

输出 manifest、来源／切分索引、事件计划、各集合 JSONL、tokenizer 和审核计数。已有输出拒绝覆盖，来源／数量／语义检查失败不写 training_allowed=true。合成时序及模板事件不能证明真实在线性能，独立文本结果仍须单独说明覆盖限制。

正常接话机会合并同轮文字到达及随后 start 锚点；持轮前缀与停顿属于同一 pause 机会。任何禁止区间错误均不能被后面的正确动作抵消。来源范围固定为 ID 10000—94999，排除历史哈希来源后取 160/200/300 对话，训练源数低于 1000 上限并如实记录。

抽检发现 Wait 已能明确表达暂停，最终规则在其首次可见时标 stop，不能等后面的 stop 字样才停止；Please 单独可见仍保持 keep。正式冻结使用 r3，r1/r2 是未训练的本地中间构建。
