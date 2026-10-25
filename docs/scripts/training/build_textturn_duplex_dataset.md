# 160ms双工数据构造

`scripts/training/build_textturn_duplex_dataset.py`是回退旧TT-010后重建的数据入口。它校验TT-001输入摘要，仅复用train160／dev200来源，构造疑问与陈述、正常完成与用户打断四种同源对照；不读test正文作为训练材料，不加载模型或调用外部服务。对照不算独立来源，所有来源组保持原切分。

`DuplexTrace`是单一模拟输出执行点，管理用户轮、版本、历史、输出ID、生成与播放游标、单调事件序号及动作快照。`step`每160ms更新可见事实，先处理已发生的播放完成，再处理用户更新并决策；同刻完成先于更新时已经Listen，监督keep而非stop。start接受后才建立输出，stop请求后80ms模拟确认才Listen；`callback`只接受一次终态并忽略过期回调，`validate`核对配对和单动作损失，截断必须明确标记。

`user_segment`按固定种子发布原文前缀，文字块之间两拍为空观察；在非末尾块后独立采样额外停顿，所有暂停拍keep。`speaking_step`以随机短附和替换一个当前用户空观察，多token附和继续逐拍到达，单独关闭到历史，助手时钟照常推进；`drain`持续观察直到真实标记为模拟的播放完成。`assistant_chunks`保持字符跨度，按3／3／2原始token循环切分。播放结束自动发布finish，不允许为了等待未来打断而无限延长Speak。

所有用户累计输入、当拍观察和用户历史均去末尾句读，原始事件只作审核保留，内部标点／小数／缩写保留。`register_finish`追加专用ID151673，原四个ID不变；事件只在首次消费时携带`<finish>`，最近终态另存，不每窗重复。模型仅监督最后的keep/start/stop ID，全部输入位置屏蔽损失；原未决前缀监督keep。手写非附和边界不进入模型输入，不代表自动语义标注。

`scenario`为每个来源按两种句式分别构造normal／interrupt，打断位置包括首次正文前、生成中和播放尾窗。`build`保留全部事件及逐前缀审核，正式采样每类最多两个重复keep，同时保留全部动作转换和外部终态消费窗，防止finish仅存在于未抽取轨迹。实际陈述start不足三分之一、快照超长或资源超限显式检查。超长窗口在完整审核中保留，正式集排除。

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false timeout 600 conda run -n interclarify-dev python scripts/training/build_textturn_duplex_dataset.py --legacy artifacts/textturn/tt-001-frozen-r3 --output artifacts/textturn/tt-010-duplex160-r2
```

产物包括切分及来源、train/dev、timelines、逐前缀标注、样例、tokenizer及配置、manifest；大文件保存在artifacts，不进Git。manifest明确training_allowed=false；后续训练需单独授权并适配新词表、嵌入和评分，不直接复用旧训练入口。失败保留部分资产，不用通过单元测试代替全量检查。

抽样机会与实际插入次数由DuplexTrace.sampling记录并在manifest汇总，独立核查入口重新计算分母；纯空白增量不算有效新输入，但必须更新原始前缀以保留后续词间空格。播放已结束时仍在到达的短附和继续在Listen接收并独立关闭，不能把未消费尾部拼进下一用户段。
