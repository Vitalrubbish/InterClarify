# Layer 1 数据核心

`scripts/training/layer1_data.py` 将已验真的 UltraChat 原始对话变为可追溯的事件计划及三组监督序列，不加载模型、不运行服务、不具有播放权。

`ReleasedTokenizer` 只用发布 `tokenizer.json` 和配置，逐项验证实际特殊 token 单 ID、EOS、无 BOS，并记录文件摘要。`user_chunks` 使用原文字符 offsets 保留跨度，不经 decode/re-encode 重建原始用户文本；遇到 Unicode 多 token 共享字符时延长到合法字符边界，因此可超过抽样的 7 token，跨度与实际 token 数保留在事件中。assistant 直接保留编码 ID，每片段最多 10 个内容 token。

`DialogueIndex` 使用 SQLite 保存原文/来源行号/摘要、排除记录、近重复倒排与并查组。`ingest` 完整流式读取所有验真 shard，先做字段/语言/长度过滤及外部排除，再精确和近重复归组。Jaccard 前缀过滤使用相同稳定 shingle 顺序，每组前缀长度为 n-ceil(0.85*n)+1，倒排完整召回阈值内候选，再精确核验交并比；128 位 shingle 摘要碰撞概率极低，但不承诺识别语义改写。`select` 按种子及原始 ID 的稳定摘要排序，去重组只选一个代表，顺序补足 1000/200/300。数量不足直接失败。

正式r1实测约4000行已产生230MiB索引后，018将抽样明确为两阶段：全库流式过滤、记录合格ID唯一性和排除原因，再按稳定哈希保留6000条候选，只有候选建立近重复图并在分组后切分。`sampling.candidate_pool_dialogues`固定预算，堆保留与源遍历顺序无关的最低排名；不截取前几个shard。最终跨split仍逐对精确核查Jaccard阈值。不对未入选语料建立近重复传递图，也不声称全库语义无重复。未配置候选预算的小型旧配置维持全量候选行为。

用户进一步取消全库过滤，当前默认通过source_records在已验真各shard上读取固定种子字节窗口，总预算raw_source_dialogues=6000；跳过起点残行、到文件末尾可回绕、同一行偏移不重复。只解析/过滤这批完整对话，记录原始byte_offset与raw_sha256，line=null表示未计算绝对行号；排除表和来源ID表也保留字节位置。未配置raw预算的旧测试配置仍支持完整扫描，但正式配置不使用该路径。不声称窗口抽样是全库逐对话均匀随机。

016外部隔离补充：逐对话检查完整文本以及每个user/assistant轮的规范化摘要，与外部清单任一项命中即排除，不再仅匹配整段对话。外部来源ID不默认当UltraChat ID；文本覆盖缺失由清单missing/reviewed显式记录。

正式全库运行时将排除ID及文本摘要在ingest入口转为集合复用，避免对每条对话重复遍历数千项；不改变匹配、事件或切分规则。

`MicroTurnPlanner.plan` 从 seed、对话 ID、epoch 派生独立随机流。按原始长轮分用户片段，插入等待/自然停顿，再输出回答片段；回答开始前抽取本长轮的插话计划，插话抢占后续附和和思考，消费原始下一用户轮且丢弃旧回答余下片段。正常回答完才采样思考。计划保存每拍 ID、用户原文跨度、控制、assistant 目标 IDs、模拟拍号，不伪造音频或真实时间戳。

`punctuation_keep_mask` 先在完整原文确定字符保护，再按冻结的用户跨度生成增强文本，跨片段的时间冒号/小数点也保留；`remove_punctuation` 处理独立文本。`mixed_assignments` 每个 split/epoch 使用独立随机流，训练集严格半数原样、半数去句读。开发/测试的计划和分配固定为 epoch 0。

`SequenceEncoder.event_ids` 手动拼接官方 raw ChatML：user header、当拍用户或 no-voice、user 消息结束及换行、assistant header、控制/正文目标与 im_end，不插入默认 system prompt。`encode` 不跨对话 packing，不截断单个 micro-turn；三视图共同最大长度决定一致窗口。后续窗口为历史预留约半个长度，携带能容纳的最近完整事件；超长历史明确受窗口限制，不声称总能保留整段请求。重叠历史、所有 user/消息头置 -100，只有当前 assistant 目标监督一次，无 padding。训练器负责 causal shift，不能再移位 labels。目标片段只有真实消息结束，不新增人工用户让轮信号。

`verify_sources` 重新核对下载清单身份、完整性、所有固定 shard 的大小/SHA256；不能只相信 complete。`validate_config` 拒绝不支持的开关、非文本附和词和非法过滤/资源范围；读取时拒收非法 Unicode。`write_json` 原子发布 JSON；稳定摘要不使用 Python 随机 hash。SQLite 建索引中断后要求换新输出，事件生成则从已完成对话游标恢复并重新校验全部输入/产物摘要。
