# 完整来源组与逐拍数据冻结

`scripts/training/freeze_textturn_full_trajectories.py`在既有160ms事件生成器上取消删拍，保持原事件、标注、随机附和／停顿和去标点规则。使用已核对的duplex160-r2作为来源，固定原ordinal及scenario_id，避免重建时悄悄改变用户检查过的70拍轨迹。

`select_whole_sources`按固定顺序累积完整来源组，下一组超预算便停止，不截断或挑其更短轨迹填空。已检查的91459优先，其余来源按固定哈希排序。每组保留疑问／陈述×normal／interrupt四条完整轨迹，维持陈述start50%。`freeze`核对基线文件摘要，选train≤10000窗、pilot≤2000窗，dev保留原200来源全部窗口；逐轨迹检查无缺帧、无超长，并为所有动作分配正权重。

冻结train21来源／9977窗，pilot4来源／1894窗，dev200来源／88947窗。保留范围内每一窗口都进入gzip JSONL并有动作损失；来源减少是10000窗上限下按完整组选择的结果。原始160来源的抽样版仍保留，不称9977窗覆盖全部160个训练来源。

产物包含split_index、selection、trajectory_index、timelines、逐前缀审核、完整70拍示例及tokenizer。manifest分开记录事件版本、数据版本、文件名、权重策略、各阶段平均权重及代码摘要；split_files指向train/pilot/dev.jsonl.gz。training_allowed=true表示数据与入口可用于本次已授权训练，不代表模型质量通过。新版本独立保存，不覆盖旧数据。

已有conda单线程CPU执行，地址空间2GiB、timeout600秒、新增资产≤512MiB：`python scripts/training/freeze_textturn_full_trajectories.py --base artifacts/textturn/tt-010-duplex160-r2 --output artifacts/textturn/tt-010-fulltraj-r1`。遇到任意超长窗口则整批拒绝交付，不通过删帧凑完整。实际构造61.438秒，资产约109MiB。
