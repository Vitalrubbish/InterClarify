# asr_delta 草稿与整段重识别覆盖测试

2026-10-30，按用户明确指令提交远端测试，逐视图反馈 `asr_delta` 形成的当前输入与原生整段 SenseVoice 返回后覆盖的输入。沿用既有检查任务，不新增 issue，不改研究范围或实现。

源码冻结为 `bd86478f8bc01cf6cb18439072ef4fa9f3263b69`，已推送 GitHub。五文件源码包经 SSH 传输，远端 SHA256 与本地一致：`e15e662d06f7a87133d952f99b1333275246c88bb91d3378abc9f3fd193758a7`。远端独立目录为 `~/parathink-soulx-duplug/source/bd86478/`，没有覆盖主仓库。

作业为 `job-179334948670207649613-xuan-zhang`，run 为 `frontend-delta-20261030-r1`，使用既有六视图 `frontend-audio-20261029-r5.json`。单作业、1×4090、4 CPU、32 GiB RAM、最长1200秒，显存22 GiB、输出128 MiB、音频积压800ms停止线。提交前队列为空、空闲磁盘约831 GiB；只读复用既有 SoulX conda、模型和加载器。

统计区分在线 Context 与合成尾部的 drain：只有在线整段结果可标为覆盖输入；没有完成分支时如实记为未发生，不额外增加识别调用。controller reset 只改变内部片段，覆盖后的全文保留此前片段。报告同时保留逐次草稿变化和完整快照证据。

## 测试结果

六视图全部完成，退出码0；实际加载、预热与回放共120.06秒。269次在线联合写入，两个读取者各281次一致；145次ASR调用无错误，六次整段结果全部在线发布，无排空ASR调用。正文实际变化109次，最大排队134.56ms，设备采样显存峰值5368MiB，未触及停止线。作业结束后队列为空。

| 视图 | 在线帧 | 内部 reset | 在线整段覆盖 | 观察 |
| --- | ---: | ---: | ---: | --- |
| original_full：原幅度完整录音 | 48 | 16 | 0 | 低音量触发频繁内部重置，草稿质量较差，没有整段纠正 |
| calibrated_full：标定完整录音 | 48 | 2 | 2 | 原句被拆为两个片段，分别修订；保留了错误断句与第二段开头的 I |
| calibrated_prefix：标定前3.2秒 | 20 | 0 | 0 | 没有进入整段完成识别，保留草稿 |
| calibrated_repeat：标定重复录音 | 97 | 4 | 3 | 第一遍分两段修订，第二遍完整修订；尾部后来又出现草稿 I |
| silence：静音 | 12 | 0 | 0 | 输入保持空字符串 |
| sensevoice_english：官方英文示例 | 44 | 1 | 1 | 草稿由整段识别覆盖；即使已发布帧未出现 user_complete，外层原生分支仍发生了整段调用 |

**逐样本完整文字与覆盖前后对照见[输入记录](sample_inputs.md)**，包含每次整段覆盖的最新增量草稿、此前实际Context、本片段识别及覆盖后实际全文，以及全部109次在线正文变化。结果由[汇总脚本](../../../scripts/analysis/summarize_soulx_context_inputs.py)直接生成，校验原始来源、实际读取与关闭正文一致。原文保留识别错误，不人为润色。

本次证明草稿和原生整段修订经过真实模型链路写入Context；没有证明整条逻辑话轮都会得到一次完整音频重识别。原生controller可在句中提前完成或重置，因此整段识别实际作用于当前controller片段，仍可能留下错误分段、漏词或末尾未修订草稿。未扩大音频集或新增识别策略。

## 证据与复现

本地完整证据：`artifacts/soulx/20261030-delta-context-r1/evidence/`；逐项校验20份载荷全部通过。下载包109944字节，SHA256为 `2e759748af41d924e05fa14c131f99597cc5da3b036784254b2b964201138538`，与远端一致。清单摘要为 `7bea1c690682d1f5f3764f6749b2df2739fced12e4e58c86dde3facf6e3bb8eb`，与旧六视图测试相同。远端输出为 `~/parathink-soulx-duplug/runs/frontend-delta-20261030-r1/`，提交命令与回执在 `submit_logs/frontend-delta-20261030-r1.*`。

本地整理使用既有 `interclarify-dev` conda：

```bash
conda run -n interclarify-dev python scripts/analysis/summarize_soulx_context_inputs.py \
  --replay artifacts/soulx/20261030-delta-context-r1/evidence/replay \
  --output reports/soulx/20261030-delta-context-test
```

脚本只整理证据，无模型调用；完整逐项源文件摘要、配置、原始ASR、状态、快照、退出码和显存采样均保留。机器可读 `inputs.json` 放入本地证据根目录，中文正文表纳入Git。
