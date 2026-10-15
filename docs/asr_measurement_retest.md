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
- 提交成功不等于测试通过；官方对齐评分尚未提交。
