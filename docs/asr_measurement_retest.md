# ASR 文本停滞与测量口径修复复测

## 目标与版本

2026-10-15 用户授权启动远端复测。实现版本为 InterClarify `304c62e`，X-Talk 为 `2f2ed0c`；任务单提交只增加本文。对照轮为 `20261015T060611Z`。本轮使用独立 git checkout 和逐文件 SHA256 manifest，提交后不修改快照。

## 运行范围

- 先运行 `pause` 暂停／恢复场景，再运行 `normal`、`interruption`。暂停专项首先检查 ASR 日志中的分段状态重建与累计文本增长，回放场景的 PASS 本身不能证明识别质量。
- 继续使用 Qwen3-ASR、MOSS-TTS 与官方 DuplexCascade 权重，ASR 分块及 micro-turn 均为 600 ms。
- FDB v1.0 沿用原五个子集，各取排序后的前 5 例，共 25 例；包括 Candor/synthetic pause、Candor turn taking、synthetic interruption、ICC backchannel。
- 输入结束后保留默认 5 秒诊断窗口；官方输出仍裁剪／补零至输入时长，诊断副本单独保存，不进入官方输出树。
- 三卡推理作业关闭官方评分；推理结束后再单卡对齐与评分，避免空闲 GPU 回收。

## 检查与结果边界

检查 `services/asr.log` 中的 session、segment、raw/visible 文本、冲突与停滞记录；确认 final 后恢复说话会进入新 segment，检查重复和遗漏。会话内深层回写冲突仍可能产生停滞，不以重建成功代替质量评估。

延迟按 request/response ID 关联，分别观察模型首 token、TTS 首 PCM、客户端首播放及旧回答停止。缺失关联保留空值。官方词级延迟由对齐器单独产生，PCM 不代替词起点。另比较评分窗口内无音频与窗口外迟到回答。

产物写远端主仓库 `data/runs/<tag>/` 与 `reports/duplex_acceptance/<tag>/`；独立源码位于远端 `interclarify-retests/<tag>/`。作业编号、manifest 和提交日志在启动后记录。未取得实际输出前，不宣称停滞消除或延迟改善。

## 提交记录

- 运行标识：`20261015T114708Z`。
- 推理作业：`job-179206501490891219471-xuan-zhang`，4090 分区，3 GPU / 24 CPU / 96 GB。
- 快照主仓库：`6eda859`（相对 `304c62e` 只增加任务单）；X-Talk：`2f2ed0c`。
- Manifest：177 个文件，SHA256 `8c7495e17eed60a9e7491af94c932f08aab14ce0ce5d2e5ada94e558b60b6a25`。
- 远端原始产物：`/mnt/cloudstorfs/sjtu_home/xuan.zhang/InterClarify/data/runs/20261015T114708Z/`。
- 提交成功不等于测试通过。

## FDB 对齐与评分

2026-10-15 在远端 debug GPU 节点（`d6-hpc-debuggpu-001`，RTX 2080 Ti）对 `20261015T114708Z-r1` 的 FDB v1.0 输出树做官方对齐与评分。推理作业（`20261015T114708Z`）在 `official_model_smoke` 后被中断，随后以同一份快照（`6eda859` / X-Talk `2f2ed0c`）重跑得到 `-r1`；`-r1` 已完成 `fdb_inference`（五轴各 5 例，全 PASS），作业内按配置跳过评分。

- 环境：`full-duplex-bench`（torch 2.6.0+cu126、NeMo 2.6.2、`NUMBA_CUDA_USE_NVIDIA_BINDING=0`），上游 FDB 固定在 `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`。
- 对齐：官方 `get_transcript/asr.py`（NeMo `nvidia/parakeet-tdt-0.6b-v2`）对五轴各 5 例产出 `output.json`，**25/25 成功**；`user_interruption` 按 `interrupt.json` 先截断再转写。
- 非 judge 轴评分：官方 `evaluation/evaluate.py`（`pause_handling` 两子集、`smooth_turn_taking`、`backchannel`）。
- `user_interruption` 的 GPT judge 使用**官方固定模型 `gpt-4-turbo`**。当前 OpenAI 兼容端点（`https://api-2.xi-ai.cn/v1`）对该模型返回「无可用通道」（端点只剩 `gpt-5.x`/`gpt-6.x`）。为保持官方评分口径，**硬等** `gpt-4-turbo` 恢复，不改用其它模型；恢复后自动补跑并回填分数。

| 轴 | 指标 | 上一轮 `20261015T060611Z` | 本轮 `20261015T114708Z-r1` |
| --- | --- | --- | --- |
| `smooth_turn_taking`（candor） | TOR ↑ | 0.80 | 0.80 |
| | Latency ↓ | 2.558s | 2.838s |
| `pause_handling`（synthetic） | TOR ↓ | 0.00 | 0.00 |
| `pause_handling`（candor） | TOR ↓ | 1.00 | **0.40** |
| `backchannel`（icc） | TOR ↓ / Freq ↑ / JSD ↓ | 0.20 / 0.0000 / 1.0000 | 0.00 / 0.0048 / 0.9545 |
| `user_interruption` | GPT / TOR / Latency | 4.60 / 1.00 / 2.848s | 待 judge（对齐 5/5 已完成） |

结论边界：`candor_pause_handling` 的 TOR 由 1.00 降到 0.40，是"ASR final 后重建分段、不再复用冲突状态"修复后的直接收益；`synthetic_pause_handling` 维持 0.00。`backchannel` 仍属设计边界（阶段 A 关闭系统附和），TOR=0.00 只说明"不抢话"，Freq 0.0048 与 JSD 0.9545 是随之而来的现象值。`smooth_turn_taking` 与上一轮持平。`user_interruption` 的分数在 judge 恢复前不作任何结论。

评分脚本（远端运行目录 `data/runs/20261015T114708Z-r1/` 下，属运行产物而非仓库代码）：

- `score_fdb.sh`：五轴对齐 + 非 judge 轴评分。评估器一律从工作副本的 `evaluation/` 目录运行，以满足 `eval_backchannel.py` 对相对路径 `./icc_gt_distribution.json` 的依赖（节点作业内联评分路径用 `$RUN_DIR` 作 cwd，会在此处失败）。
- `judge_fdb.sh`：每 300s 探测一次端点；`gpt-4-turbo` 可用后以 `--skip-align` 复用对齐结果补跑官方 judge，退出码与产物写入 `scoring/synthetic_user_interruption/`。

证据已复制到 `reports/duplex_acceptance/20261015T114708Z-r1/`：`fdb_axes_summary.json`、`tests/fdb_scoring_*.log` 与 `scoring/*_align_summary.json`。
