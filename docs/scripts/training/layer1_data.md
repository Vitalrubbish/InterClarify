# Layer 1 数据核心

077新增可选ASR视图：`arms_for_config`在声明`delayed_punctuation_v1`时增加ASR臂，`arm_view`统一选择视图。`MicroTurnPlanner.plan`在原计划完成后调用`apply_asr_surface`追加可见文本和来源，不更改随机事件或目标；旧配置不调用该过程。`SequenceEncoder.event_ids`读取`user_asr`，窗口共同长度同时考虑ASR视图，用户文本仍全部mask。规则说明见[asr_surface.md](asr_surface.md)。

`scripts/training/layer1_data.py` 将已验真的 UltraChat 原始对话变为可追溯的事件计划及三组监督序列，不加载模型、不运行服务、不具有播放权。

`ReleasedTokenizer` 只用发布 `tokenizer.json` 和配置，逐项验证实际特殊 token 单 ID、EOS、无 BOS，并记录文件摘要。`user_chunks` 使用原文字符 offsets 保留跨度，不经 decode/re-encode 重建原始用户文本；遇到 Unicode 多 token 共享字符时延长到合法字符边界，因此可超过抽样的 7 token，跨度与实际 token 数保留在事件中。assistant 直接保留编码 ID，每片段最多 10 个内容 token。

019修复后，`MicroTurnPlanner` 在原始随机分片之后、事件生成之前，将去句读后为空的标点片段合入相邻用户片段。合并记录次数和超过7基础token的片段数；这些片段不再变成 no-voice。`DialogueIndex.rejection` 排除任何去句读后整体为空的用户长轮。这样保持原始跨度、三视图共同边界与控制目标，同时承认合并是相对论文严格1–7 token的一项例外。

`DialogueIndex` 使用SQLite保存抽样对话的原文/来源位置/摘要、排除记录、近重复倒排与并查组。`ingest`只处理source_records给出的有界完整对话，先做字段/语言/长度过滤及外部排除，再精确和近重复归组。Jaccard前缀过滤使用相同稳定shingle顺序，每组前缀长度为n-ceil(0.85*n)+1，倒排完整召回候选，再核验交并比；不承诺语义改写识别。`select`按种子及原始ID稳定排序，每个近重复组只选一个代表，顺序补足1000/200/300，数量不足失败。

`source_records`默认在已验真各shard读取固定种子字节窗口，总预算raw_source_dialogues=6000；跳过起点残行、文件末尾可回绕、同一行偏移不重复。只解析/过滤这些完整对话，记录原始byte_offset与raw_sha256，line=null表示未计算绝对行号；排除表和来源ID表也保留字节位置。未配置raw预算的旧测试配置保留完整扫描分支，正式配置不使用。窗口抽样不主张全库逐对话等概率。最终跨split另做逐对近重复审计。

016外部隔离补充：逐对话检查完整文本以及每个user/assistant轮的规范化摘要，与外部清单任一项命中即排除，不再仅匹配整段对话。外部来源ID不默认当UltraChat ID；文本覆盖缺失由清单missing/reviewed显式记录。

正式全库运行时将排除ID及文本摘要在ingest入口转为集合复用，避免对每条对话重复遍历数千项；不改变匹配、事件或切分规则。

`MicroTurnPlanner.plan` 从 seed、对话 ID、epoch 派生独立随机流。按原始长轮分用户片段，插入等待/自然停顿，再输出回答片段；回答开始前抽取本长轮的插话计划，插话抢占后续附和和思考，消费原始下一用户轮且丢弃旧回答余下片段。正常回答完才采样思考。计划保存每拍 ID、用户规范化跨度及完整原文映射、控制、assistant 目标 IDs、模拟拍号，不伪造音频或真实时间戳。

`punctuation_keep_mask` 先在完整原文确定字符保护，再按冻结的用户跨度生成增强文本，跨片段的时间冒号/小数点也保留；`remove_punctuation` 处理独立文本。`mixed_assignments` 每个 split/epoch 使用独立随机流，训练集严格半数原样、半数去句读。开发/测试的计划和分配固定为 epoch 0。

`SequenceEncoder.event_ids` 手动拼接官方 raw ChatML：user header、当拍用户或 no-voice、user 消息结束及换行、assistant header、控制/正文目标与 im_end，不插入默认 system prompt。`encode` 不跨对话 packing，不截断单个 micro-turn；三视图共同最大长度决定一致窗口。后续窗口为历史预留约半个长度，携带能容纳的最近完整事件；超长历史明确受窗口限制，不声称总能保留整段请求。重叠历史、所有 user/消息头置 -100，只有当前 assistant 目标监督一次，无 padding。训练器负责 causal shift，不能再移位 labels。目标片段只有真实消息结束，不新增人工用户让轮信号。

`verify_sources` 重新核对下载清单身份、完整性、所有固定 shard 的大小/SHA256；不能只相信 complete。`validate_config` 拒绝不支持的开关、非文本附和词和非法过滤/资源范围；读取时拒收非法 Unicode。`write_json` 原子发布 JSON；稳定摘要不使用 Python 随机 hash。SQLite 建索引中断后要求换新输出，事件生成则从已完成对话游标恢复并重新校验全部输入/产物摘要。

r5由normalize_user_text在完整用户长轮上生成英文数值读法和替换映射。MicroTurnPlanner.plan保存user_turns，事件原点跨度指向规范化文本；DialogueIndex.rejection排除歧义/不支持数值上下文。大小写、撇号及assistant正文保留，数字转换在分拍前完成。

r5同时以原始文本与数值规范化后的文本进行切分前近重复分组、切分后跨集合审计，避免书面数字和英文数词在转换后变成跨集合重复；外部排除摘要也检查规范化后的用户文本。

## Issue 040：下一无文本拍启动

为检验静音中启动回答的监督，当前唯一时序将普通用户末片段独立记录为 `user_final_wait`，目标为 talking 和 EOS；紧接的空用户拍记录为 `response_start`，目标为 finish、原首回答片段及 EOS。单片段插话保留当拍 interruption，下一拍直接 response_start，不增加额外等待拍。no-voice 仅表示当拍无新增识别文本。

新模式不额外消耗随机数，用户分片、句内暂停、插话截断、附和、思考和回答内容与同种子旧计划一致。每个用户来源跨度仅出现一次。三视图共享事件，窗口和 mask 仍由原编码器重建。代码不再提供 `same_user_chunk` 分支或配置开关；旧 r5 同拍数据只能按固定 Git 提交追溯。当前正式数据按该固定时序构建。
