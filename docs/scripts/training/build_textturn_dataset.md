# TextTurn 数据构建入口

对应实现：`scripts/training/build_textturn_dataset.py`。TT-001 当前交付480ms合成检查批次，正式来源及切分尚未冻结，不启动训练。

## 来源与编码

`fetch_preview` 只下载固定revision的UltraChat分片前1MiB、来源API和Qwen3-0.6B tokenizer，不加载模型。校验HTTP范围、revision及缓存SHA256；没有整分片LFS校验，不冒称恢复旧训练产物。`read_sources`只读取完整行，保留来源ID、行摘要和字节位置。新增文本必须声明synthetic_annotation。

`ControlTokenizer` 注册独立keep/start/stop/no-voice token，不沿用旧数值ID。`chunks`按token offset取原始字符区间；User传入1—2的随机预算及显式种子，Assistant传入8的固定生成预算。Unicode重叠区间与User孤立末尾句读合并，可能偶尔超过预算，保留全部字符。Assistant保留句读；末片可小于预算。

## 逐窗状态与监督

`compile_scenario`使用配置的window_ms=480，与底层ASR名义160ms区分。每窗先发布User和Assistant新增文字，再生成控制快照。emit_step累加已生成的助手前缀，记录当前生成是否完成、连续空观察窗数及当前Listen/Speak；不把未来正文、计划等待长度或标注理由放入输入。

seeded_rng用种子、场景采样组及阶段编号派生随机数，顺序变化不改变结果。sampling_group可用于需要共用分片的对照；本批六条综合轨迹独立派生各自的随机调度。话中停顿在已审核位置随机1—3窗，较长停顿例分层取2—3窗；原始毫秒时长按ceil(duration/480)量化并记录误差。

Speak保持到playback_complete。generation阶段持续发布8-token片段，最后一片后assistant_generation_complete=true，不自动切Listen。playback_tail要求生成已结束，随机等待1—3窗，助手无新文本但仍Speak。playback_complete是无动作的状态事件，把已完成助手正文写入历史并转Listen；post_playback_wait随机等待1—5窗，模拟下一轮开口前等待，不等同真实认知时间。

每个观察窗都保留一个动作快照，合法动作仅Listen/keep、Listen/start、Speak/keep、Speak/stop。stop阶段前缀须显式指定prefix_action，在已审核trigger_text首次可见时标stop；后续已计划的用户文字继续在Listen到达。start阶段只允许一个明确让轮空窗，assistant_stream在该阶段指定随后要生成的来源。没有动作标注的输入仍全部屏蔽损失，不自动填keep。

综合轨迹的control_applied事件模拟唯一仲裁执行点接受当前监督动作：start前的快照仍是Listen，随后提交已到达用户正文、清空当前用户缓冲并转Speak；下一窗才发布助手增量。stop前快照仍是Speak，随后停止本轮生成，把已生成前缀以generated_only/interrupted保留，转Listen并保留已到达的打断文字；不把未生成或未确认已播内容写成完整回答。用户短附和结束时可显式close_backchannel，把短回应写入带backchannel标记的历史并清空当前用户缓冲，助手继续Speak。生成与播放完成后可接下一轮，时钟不重置。

phase的category和utterance_form只用于监督统计，不进入模型输入。轨迹总体标mixed，各类覆盖按轨迹／来源组分别统计；在任一动作后都可以继续后续阶段，不再强制截断。样例表显示状态执行事件，完整历史保留在同一条轨迹中。这些是数据中的模拟执行，不接入真实仲裁器或播放器。

snapshot仅把最后的动作token作为预测目标，用户和助手正文均不计算损失。超过2048 token的记录保留并排除，不能截断关键历史。连续空窗数只反映已观察的窗口，播放完成后按新一轮等待重置。

## 输出与边界

`group_sources`在所选来源内做归一化五词shingle及Jaccard≥0.85去重，不声称覆盖全库。`build`检查来源摘要、资源规模和动作损失位置，记录类别、token数、各类空窗和生命周期统计。最多2000个检查快照，非空输出目录拒绝覆盖。

输出包括逐窗timelines.json、带输入和labels的review_samples.json、JSONL候选、来源、manifest及audit。samples.md先给每窗新增文本、当前状态和动作token的紧凑表，完整历史与标注理由放在可展开区。动作均为监督目标，不是模型实测输出。

本轮仅在已有conda interclarify-dev中做单线程CPU数据构造与少量测试；Nemotron三步聚合及真实LLM/TTS时间戳仍待TT-003/004，未修改现役服务。

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
conda run --no-capture-output -n interclarify-dev python scripts/training/build_textturn_dataset.py \
  --cache artifacts/textturn/tt-001-pinned-preview --output artifacts/textturn/new-review
```

结果和缺口见[报告](../../../reports/textturn/20261024-tt-001-preview/README.md)。
