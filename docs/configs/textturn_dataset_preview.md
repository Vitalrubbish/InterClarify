# TextTurn 检查批次配置

对应文件：`configs/textturn_dataset_preview.json`，仅供TT-001检查，不是正式训练放行配置。

按用户2026-10-25指令，window_ms=480、user_tokens_per_step=[1,2]、assistant_tokens_per_step=8、seed=20261025。User按固定种子随机分片；Assistant的8 token描述模拟生成，不代表语速或实测LLM吞吐。底层ASR仍为160ms，后续在线接入按三个完成步骤聚合控制窗，转写每次及时写Context。

history_before_turn指定已完成历史；assistant_stream引用当前助手来源，assistant_lead_in_steps=2用于附和／打断前的生成片段；sampling_group使配对场景共用随机分片。原文区间右开，新增表达显式标synthetic_annotation。

phases支持user、silence、generation、playback_tail、playback_complete、post_playback_wait。话中silence在已审核不完整表达处随机1—3窗，较长停顿例使用2—3窗；完整用户表达后的首个允许让轮空窗标start。自然结束先完成generation，再随机1—3窗保持Speak，收到播放完成事件后转Listen，再随机1—5窗等待下一轮开口。计划尾窗长度不作为控制输入。

三个短附和仍为Hmm.、Right.、I see.，按当前上下文保持keep。打断阶段用人工核对的trigger_text定位首个停止依据可见的窗，之前显式标prefix_action=keep；不等完整后续请求。额外保留生成已结束、音频仍在播放时用户打断的对照。

本配置没有类或方法；构建器在窗口、随机预算和生命周期处拒绝无效参数。所有来源及派生保持review集合，正式切分和独立性缺口见gaps_zh。
