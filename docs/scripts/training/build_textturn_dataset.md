# TextTurn 数据构建入口

对应实现：`scripts/training/build_textturn_dataset.py`。本次交付 TT-001 的来源可追溯检查批次，正式规模及旧切分尚未恢复，工作单继续实施中，不放行训练。

## 功能与输入

`--fetch-preview` 只下载固定 revision 的 UltraChat `train_0.jsonl` 前 1MiB、来源 API 和 Qwen3-0.6B tokenizer，不加载模型。要求 HTTP 206 且 Content-Range 精确一致，单资源读取有上限。API 验证别名跳转后的 revision，下载清单记录 URL、范围、大小和 SHA256；没有整分片 LFS 校验，不能声称完整来源验真。

`--config` 读取逐例语义计划。原文引用使用 source_turn 和字符区间，新增用户表达必须显式标 synthetic_annotation。仅取完整 JSONL 行，保留原始行哈希与字节位置。当前配置所有来源均属 review 集合，不分配 train/dev/test；原来 train_0 是上游分片名，不是本项目训练切分。

## 类与核心方法

`ControlTokenizer` 从固定 Qwen3 tokenizer 注册 keep/start/stop 和 no-voice 四个独立 token，验证它们都位于原词表末尾之后；不引用旧 DuplexCascade 数值 ID。`chunks` 根据原文 token offset 切分，默认每两 token，合并 Unicode 重叠区间，保留全部字符。User 的孤立末尾句读并入前一片段，避免去句读后凭空产生 no-voice 观察；Assistant 按 assistant_tokens_per_step 切分，保留独立句读末片。Unicode 或 User 句读合并可偶尔超过两 token，不能拆坏字符。

`compile_scenario` 顺序消费计划，只把当前可见历史、用户累计文本、助手已生成／模拟播放可见文本、Listen/Speak、本步观察和空 CoT 写入 prompt。计划类型、未来文本、标签及标注理由都放在输入外。每个非空片段计 160ms；空窗按 ceil(duration/160) 重建，600ms 为四步／640ms，1200ms 为八步／1280ms。当前新增停顿为合成设置，没有冒称恢复旧停顿位置。

Speak 场景从空助手前缀开始，emit_step 在每个 160ms 步骤发布一个助手片段并累加 assistant_visible；User 到达或无新增文字时都按同一时钟推进。assistant_lead_in_steps 只推进时间线，快照仍取既定锚点。事件记录本步助手增量、累计前缀及 token 数，可逐窗检查。配置使用 assistant_stream 提供来源，不再接受旧的固定 assistant_visible 片段。

仅在逐例语义锚点输出快照，action=null 表示未提供动作监督，全部 labels=-100；默认说明只记录未标注，不把它解释为语义歧义。可以依据当前上下文判断的记录，应在配置中显式填写动作及理由，不在构建器中自动填 keep。当前检查批次已逐条补齐七个 keep，不再有空标签。已标注快照在输入末尾附一个动作 token，只该位置参与损失；其余输入及回答正文都被屏蔽。按 causal LM 的常规左移损失使用。超过 2048 token 的记录保留并排除，不截断历史。当前完整输入按固定 ChatML 模板关闭 thinking，保存 tokenizer 和 tokenizer_config，不输出解释。

`playback_complete` 是运行状态事件，要求当前助手来源已全部发布，再将 Speak 改为 Listen，不产生 stop 目标。最后一片发布不自动转 Listen，保持生成与播放生命周期分开；start/stop 后必须结束本场景，防止继续沿用过期状态。助手文本与播放状态均为合成，未发布的回答不进入输入，不能据此宣称真实 TTS 已按相同节奏播放。

`group_sources` 对本批所选来源做 NFKC／大小写归一化后的五词 shingle 比较，Jaccard≥0.85 的对话归为同组。当前只检查六个来源，不声称覆盖全库或全部模板派生。

`build` 校验缓存摘要，输出原文、完整事件时间线、含输入与 loss mask 的检查快照、候选 JSONL、中文阅读版和数量清单；逐例核对动作损失位置，并记录最大输入长度、类别数量和去重结果。配置与实现摘要写入 manifest；已存在的非空目录拒绝覆盖。最多 2000 检查快照，正式候选规模上限仍以工作单为准。本入口当前不提供正式数据切分或训练放行功能。

检查 JSON 按快照紧凑存储，避免 token 数组产生大量无意义换行；人工阅读使用单独的 samples.md。

## 复现与结果

本地使用已有 conda 环境 `interclarify-dev`，这是项目约定允许复用的环境。只做 CPU 数据准备与契约测试，线程设为 1；无 GPU、远端调度或模型测试。本次远端仅只读核查来源目录、活动作业与磁盘。

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
conda run --no-capture-output -n interclarify-dev python scripts/training/build_textturn_dataset.py \
  --fetch-preview --cache artifacts/textturn/pinned-preview

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
conda run --no-capture-output -n interclarify-dev python scripts/training/build_textturn_dataset.py \
  --cache artifacts/textturn/pinned-preview --output artifacts/textturn/review-preview
```

检查材料与缺口见[本次报告](../../../reports/textturn/20261024-tt-001-preview/README.md)。用户审核这些样例不能替代全量来源核查、独立测试隔离和实际 Nemotron 回放。
