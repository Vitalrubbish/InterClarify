# TT-001：480ms控制窗检查批次

更新：2026-10-25。按用户最新指令，控制窗改为480ms，User非空窗随机1—2 token，Assistant每窗8 token模拟LLM生成。生成完成、剩余音频播放、下一轮用户开口前等待分别建模。此前160ms／24锚点批次已被替换，历史证据保留在Git。

**TT-001仍实施中，本批全部为review，不放行训练或独立测试。** 未加载模型、运行GPU或替换现役服务。原始来源和旧切分缺口仍未解决。

直接查看[逐窗阅读表](samples.md)；表中列出双方本窗新增、Listen/Speak、生成是否完成、连续空窗数和动作token。完整输入与loss mask见[review_samples.json](review_samples.json)，原文、时间线和统计分别见[source_records.json](source_records.json)、[timelines.json](timelines.json)、[manifest.json](manifest.json)。动作是监督目标，不是模型实测输出。

## 当前参数和数量

| 项目 | 当前值 |
| --- | --- |
| ASR名义解码步骤／控制窗 | 160ms／480ms；在线聚合待TT-003 |
| User非空输入 | 按种子随机1—2 token／窗 |
| Assistant模拟生成 | 8 token／窗；末片可更短，不按语速解释 |
| 来源对话／去重组／场景 | 6／6／15 |
| 窗口及有标签快照 | 118；未标注0 |
| keep／start／stop | 110／4／4 |
| 完整陈述start | 2／4，50% |
| 无新增用户文字的窗 | 38／118；不等同声学静音 |
| Assistant非空生成窗 | 34；32窗各8 token，2个末块各7 token |
| 最大输入／超长排除 | 718 token／0 |
| 正式train／dev／独立test | 0／0／0 |

四类不同来源组：正常接话4、打断4、附和3、内部停顿2，另有自然完成2组；这些有重叠，不能相加冒充独立对话数。正式目标仍为最多1000训练对话／10000快照、200开发及300独立测试对话，测试四类各至少100个场景组，当前不满足。

## 生成完成后还有什么

以natural_completion_2为例，用户原问题为海洋覆盖率。Assistant以8-token块生成原回答的完整一句；下表只展开关键窗口，逐窗细节见samples.md。

| 时刻 | 观察阶段 | 状态 | User新增 | Assistant新增 | 目标 |
| --- | --- | --- | --- | --- | --- |
| 480ms | LLM仍在生成，音频播放中 | Speak | no-voice | 首8 token | keep |
| 960ms | LLM生成结束 | Speak | no-voice | 剩余7 token | keep |
| 1440—2400ms，共3窗 | 无新文本，尚有播放尾巴 | Speak | no-voice | 无 | 每窗keep |
| 2400ms，状态事件 | playback_complete | Speak→Listen | — | — | 不输出stop |
| 2880—4320ms，共4窗 | 等待用户下一轮开口 | Listen | no-voice | 无 | 每窗keep |

播放尾窗只模拟生成结束时剩余未播完的部分，不额外加一遍整段语音长度。下一轮等待是开口前的剩余等待，不推断真实认知过程。另有interruption_playback_tail：LLM已经生成完，但播放仍在继续，用户要求stop时仍标Speak/stop。

## 构造与可见性

- 固定种子20261025，User随机分片预算1—2 token；实际81个非空用户窗中26窗为1 token、53窗为2 token，两个带原始句读的末片为3 token。字符边界和句读合并保留原文，不为严格凑预算丢字符。
- 话中停顿只在已审核的不完整表达处插入随机空窗，一例取1—3窗，较长例分层取2—3窗。完整问题后的首个允许让轮空窗标start，所有可见观察窗都有监督，未只取阶段末尾。
- 自然完成场景的剩余播放尾巴随机1—3窗，播放完成后的下一轮等待随机1—5窗。当前两例分别抽到3／1个播放尾窗和各4个下一轮等待窗；计划长度不进入输入。
- 控制输入新增window_ms、连续no-voice窗数和assistant_generation_complete。它们只描述已经观察到的时间及当前生成状态，不暴露未来等待时长。相同文字下的连续空窗因此可区分；播放完成后按下一轮等待重置计数。
- Assistant输入只累加已生成的正文；生成结束后保持完整已生成正文，Speak仍由播放状态维持。正常播放完成没有stop标签。打断依据首次可见即标stop，不等后续完整请求。
- Nemotron底层160ms步骤保留；TT-003再实现三步聚合成480ms控制窗，ASR更新仍及时写Context。聚合等待必须单列并纳入及时性评分，不后移评分锚点。

## 验证与来源限制

七项CPU契约测试通过，实际Qwen tokenizer核查118个窗口／动作mask、34个助手前缀、18个用户阶段字符往返、tokenizer重载和全部prompt模板。全量重建结果可复现；配对I see前缀输入一致，生成结束后的尾窗打断仍为Speak/stop。详见[audit.json](audit.json)、[verification.json](verification.json)及[sha256.json](sha256.json)。本地复用conda interclarify-dev，线程1；没有集群模型测试。

来源仍是UltraChat固定revision f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0的train_0.jsonl前1MiB，仅使用完整行并记录原始行哈希及字节位置。旧别名stingning/ultrachat跳转openbmb/UltraChat后revision一致；未下载整分片校验LFS。tokenizer固定Qwen3-0.6B@c1899de289a04d12100db370d81485cdf75e47ca，动作token与no-voice由本次注册，不沿用旧ID。

没有真实Nemotron、LLM或TTS时间戳，8 token和随机等待只是可复现的合成起点，不能宣称已经匹配真实输出或播放分布。旧来源分组、切分、测试使用历史、正式规模和独立测试语音仍有缺口，因此training_allowed=false、independent_test_ready=false，TT-001不归档。

实现为[构建器](../../../scripts/training/build_textturn_dataset.py)，参数见[配置](../../../configs/textturn_dataset_preview.json)，复现见[中文说明](../../../docs/scripts/training/build_textturn_dataset.md)。完整tokenizer与JSONL留在本地artifacts/textturn/tt-001-review-final，不重复提交大tokenizer。报告目录日期保留首次交付日期，内容按本页更新日期为准。
