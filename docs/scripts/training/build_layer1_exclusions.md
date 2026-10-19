# 构建外部评测排除清单

`scripts/training/build_layer1_exclusions.py`读取真实FLEURS manifest、历史Word manifest及FDB原始JSON，输出004可消费的排除清单，无业务类。

`extract_text`只递归读取配置中的文本字段并去除标注占位符。`build`核验各集合样本数、保存逐样本ID/文件摘要/文本数量，加入每个文本单元及完整样本拼接的NFKC词归一化摘要；历史Word事件额外按原顺序拼接，防止仅保存单词摘要而漏掉整句。外部ID只作溯源，ids默认空，避免与UltraChat误撞。

实际FLEURS清单含100条test及1条dev诊断录音，100条门槛按test计数，所有101条均加入排除，不丢弃已有dev材料。

缺转写/目录缺失/样本数不符都写missing，只有所有登记样本具有文本才reviewed=true；机器覆盖齐备也不自动放行训练。异常JSON不静默跳过。命令必须显式传入`--fleurs-manifest`、`--historical-manifest`、`--fdb-root`、`--output`，配置默认configs/layer1_exclusions.yaml。

`layer1_data.DialogueIndex.ingest`已同步检查完整对话及每轮文本摘要；这仍只是明确规范化规则下的精确文本隔离，不承诺ASR改写或任意语义近重复都能被识别。
