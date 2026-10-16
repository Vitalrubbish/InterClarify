# prepare_asr_selection.py

准备三款 ASR 的不可变模型快照和 FLEURS 英文固定子集，不执行推理。无业务类。

`prepare_models` 按 Hugging Face revision 下载 Transformers 格式 Nemotron 和原生 Moshi 格式 Kyutai，保留模型配置、许可证与各文件 SHA256。Kyutai 的 Mimi 配套权重也单独固定。`prepare_data` 固定 FLEURS revision，读取官方 TSV 的原始及规范化转写，从 test 音频包中只提取确定性选择的 100 条，dev 独立取一条预热，写共用 manifest。归档按精确成员读取，不允许路径穿越。

下载可重试并利用 hub 缓存。数据、权重、版本清单位于远端独立实验目录，不进入 Git。

FLEURS TSV 按不解释引号的制表符格式读取，避免参考文本中的引号导致跨行合并。`--candidate` 可独立下载某个模型，其独立 lock 文件避免并发覆盖；完整运行汇总为 `models.lock.json`。Kyutai 配套 Mimi 若随主 repo 发布，直接复用同一固定 revision 的文件。
