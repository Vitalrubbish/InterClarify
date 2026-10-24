# TT-001 首批数据检查材料

2026-10-24，按用户“启动 TT-001，并提供数据示例检查”的指令交付。状态：**TT-001 实施中；本批为 review 样例，正式数据尚未冻结**。未加载模型、训练或执行 GPU 作业。

直接查看[逐例中文阅读版](samples.md)，或下载[含实际输入、动作 token 和损失 mask 的 JSON](review_samples.json)。原文、完整时间线及清单分别见 [source_records.json](source_records.json)、[timelines.json](timelines.json)和 [manifest.json](manifest.json)。所有样例属于 review 集合。

## 本批数量

| 项目 | 实际数量 |
| --- | --- |
| 原始 UltraChat 对话／本批去重组 | 6／6 |
| 合成场景 | 14 |
| 决策快照 | 27 |
| 有标签／未知 | 16／11 |
| keep／start／stop | 9／4／3 |
| 正常 start 中完整陈述 | 2／4，50% |
| 超长排除 | 0；最大输入 669 token |
| 正式 train／dev／独立 test | 0／0／0 |

四类场景的不同来源组分别为正常接话 4、用户打断 3、用户附和 3、内部停顿 2；另有自然完成负例 2 组。这些组有重叠，不能相加当作独立对话总数。正式目标仍为训练最多 1000 对话／10000 快照、机制试训最多 2000 快照、开发 200、独立测试 300 对话，测试四类各至少 100 个不同场景组，当前均未满足。

## 先看这几条

下表为完整样例的节选；历史及助手当前可见片段请以对应 JSON／阅读版为准。

| 场景与状态 | 当时可见用户文本 | 本步观察 | 目标动作 | 依据 |
| --- | --- | --- | --- | --- |
| 陈述接话，Listen | Wow, that's a lot of water! No wonder we call it the blue planet | no-voice | start | 完整感想后留出空窗，陈述也可正常回应 |
| 内部停顿，Listen | How can cross training benefit groups like | no-voice | keep | “like” 后的对象尚未出现，空窗不能补全句意 |
| 附和，Speak | That makes sense, please keep going | keep going | keep | 用户明确请系统继续 |
| 打断，Speak | That makes sense, but please stop now | now | stop | 用户明确要求停止 |
| 共用前缀，Speak | That makes sense | sense | unknown | 同一历史和助手片段下，两种后续尚不可见，不能提前确定标签 |
| 自然说完前，Speak | （本轮没有用户新增文本） | no-voice | keep | 仍在播放时保持 keep；播放结束事件直接转 Listen，不标 stop |

表中本步非空观察的实际字符片段以 JSON 为准，可能包含前导空格或部分单词；没有等待完整词。前缀对照的两个 prompt 完全一致，已做相等检查。未知样例 labels 全为 -100；有标签样例只在最后一个动作 token 上计算损失。

## 来源、时序与核查

- 来源固定为原计划的 `stingning/ultrachat@f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0`；请求转向 `openbmb/UltraChat` 后，[官方 API](https://huggingface.co/api/datasets/openbmb/UltraChat/revision/f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0)仍返回同一 revision。只下载 `train_0.jsonl` 的前 1MiB，HTTP 206、范围 `0–1048575/963569677`；仅取完整行，保留来源 ID、原始行 SHA256 与字节位置。没有整分片 LFS 校验，未声称恢复旧资产。
- 使用 [Qwen3-0.6B 固定 tokenizer](https://huggingface.co/Qwen/Qwen3-0.6B/tree/c1899de289a04d12100db370d81485cdf75e47ca)，新增 keep/start/stop/no-voice ID 分别为 151669／151670／151671／151672；它们由本次注册产生，没有沿用旧控制 ID。tokenizer 重载后编码一致。
- 原文引用按字符区间保留；新增附和、停止请求在配置中显式标为合成。19 个用户文本阶段的实际 tokenizer 分片往返无字符损失。非空片段每步约 1—2 token，本批有三个片段在并入末尾孤立句读后超过两 token，保留全部字符且没有凭空增加静音步骤。
- 所有 160ms 发布时刻及 Speak 播放状态均为模拟。新增 600ms／1200ms 空窗按向上取整变为四步 640ms／八步 1280ms，未把旧 600ms 窗直接改名。当前没有真实 Nemotron trace 或可回放语音。
- 已核对六个来源与逐例锚点的可见语义，完整表达方可标 start，明确继续／停止方可标 keep／stop；没有将截断位置、末尾标点或下一轮回答作为标签依据。编码代理检查不等于人类独立复核，用户检查仍待进行。
- 本批做五词 shingle、Jaccard≥0.85 的来源去重，六个来源无匹配；仅覆盖所选来源，不声称全库或模板审查完成。

## 验证与复现

本地复用 conda `interclarify-dev`，CPU 线程上限 1。五项契约测试通过；实际 Qwen tokenizer 完成 19 阶段字符往返、四个新增 token 的重载检查、27 条 prompt 与官方关闭 thinking 模板一致、27 条动作损失屏蔽检查。结果见 [audit.json](audit.json)和 [verification.json](verification.json)。这些是数据契约检查，不是模型质量或集群测试。

实现入口为 [build_textturn_dataset.py](../../../scripts/training/build_textturn_dataset.py)，配置为 [textturn_dataset_preview.json](../../../configs/textturn_dataset_preview.json)，使用方式见[对应中文说明](../../../docs/scripts/training/build_textturn_dataset.md)。完整 tokenizer 与 JSONL 候选留在本地 `artifacts/textturn/tt-001-review-final/`，报告不提交重复的 11MiB tokenizer。

本轮远端只读检查：主机 `d6-hpc-debuggpu-001`，`vc list` 无活动作业，用户文件系统当时可用 894GiB；未创建远端作业。已检查的旧训练目录、主仓库、p0 模型目录和撤回实验归档的限定深度内，未找到旧 `dialogues.json`、UltraChat 原始分片或事件产物；这不代表已证明整台服务器没有备份。

后续仍需恢复或可核验重建旧来源／分组及切分，核对旧测试使用历史，补足正式候选和独立测试来源，完成必要语义抽查及正式冻结。因此 **training_allowed=false、independent_test_ready=false**，TT-001 不归档，TT-002 不启动。当前样例足以检查数据结构与标签方向，不能据此声称四类能力已通过。
