# ASR 接话测试的官方输入对齐复核

2026-10-18 用户要求先复核官方每拍输入，再重测接话并修正最终路线。本轮只验证固定 ASR 轨迹到官方控制权重的文本接话，不训练，不调用 TTS，不代表全链路 FDB 得分。

## 已确认的差异与修复

官方 [server.py（固定提交）](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py) 的 SHA256 为 `404a1b6f51e87c012e1111cc21a712ed8895e9a5ee99328bd1245a7c6a654037`：收到 Word 时先 `strip()`，本拍将非空 Word 用单个空格连接；模型收到的本拍文本没有前导或尾随分隔空白。旧累计前缀按字符截取后缀，会把词间空格留在新拍开头。旧 `build_prompt_ids` 虽用 `strip()` 判断空拍，却编码未经 strip 的原文，导致输入 token 与官方不一致。

这不是显示差异。用发布 tokenizer 实测，`" companies"` 的 ID 为 `[5110]`，`"companies"` 为 `[64751]`；`" that let"` 为 `[429, 1077]`，`"that let"` 为 `[9033, 1077]`。旧样本 1 的第三拍 `" that let you"` 在 prompt 索引 26（从 0 开始）首次偏离官方规则。

修复在唯一模型服务的 prompt 提交边界去除每拍首尾分隔空白，不改 ASR 已交付累计前缀，不修改标点、大小写或词内字符。空白拍映射实际 no-voice ID。补齐 tokenizer 存在 BOS 时的起始 ID，与官方条件分支一致；本权重的实际 BOS 值由远端记录。

逐项核对：user/assistant header、user 尾部 im_end+换行、空拍 no-voice、assistant 原始生成 IDs 原样回写（不额外补换行或 re-encode）、64-token 贪心生成及 im_end 结束、600ms 串行且不积压过时拍。按官方复测时钟从首个非空 ASR 输出后起拍；这与已实现的产品 F1“会话起拍”是不同实验条件，不能混称完全复现。此轮不撤销产品 F1。

ASR 发布粒度不做伪装：Kyutai 发布 Word，而 Nemotron 轨迹可能含词内增量。此次只改变 prompt 的空白规则，保留各自真实前缀与到达时刻，不为提高接话结果添加句号、延迟词提交或泄露标注边界；残余发布粒度差异需要独立解释。

## 配对复测

使用上轮同一份 `endpoint-b4d12d6` 的五例 Candor 接话真实 ASR 轨迹，以及原始/去标点两个条件。五个 ASR 配置不变。legacy 与 official 两臂各 50 条，共 100 次控制回放，模型、权重、BF16、生成预算、轨迹和观察窗口固定；每例各自生成自己的 assistant 历史。

在独立远端单 GPU conda 作业内回放，模型推理与 X-Talk 客户端使用原有隔离环境。冻结脚本和输入哈希，保留旧失败，不修改旧报告。每次请求保存原始历史、实际 prompt IDs、独立官方规则 oracle 的 IDs、一致性及差异位置；official 臂必须逐请求一致，不能仅比较解码后文字。

沿用标注用户结束后 2/5/12 秒新 response 正文启动指标；未接话保留分母，早于边界的正文、旧正文续写、仅 finish token、取消后的结果分别记录。标注边界只用于离线统计，不送入模型。延迟与输入发送迟到单列，本轮不测有声输出。

## 结论约束

旧 1/5、5/5 与标点消融结果在对齐复测前仅为受输入格式混杂影响的历史记录，不再单独据此认定需要训练。依据新结果再确定保持官方权重、进一步分离发布粒度/时钟，或开展有限适配；既有 WER 结果不因 prompt 修复而改写。

执行补充：初始两臂长作业各保留 15 条后异常结束，未取得正常退出码或调度器终止原因。正式配对结果改用每配置一个独立短作业（每臂 5 个分片、每片 10 条）完整重跑；旧部分结果不计入最终 100 条。观察窗、权重和轨迹不变，不通过人为占用 GPU 来维持作业。

## 2026-10-18 远端结果核对

本次分析只读核对远端 `interclarify-asr-alignment-20261018-final/runs/` 的 `control/results.json`、已存在的 `summary.json`、`exit_code.txt` 和异常日志，没有启动新的推理或训练。任务根绝对路径为 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-alignment-20261018-final/`。

| 配置 | legacy 原样 / 去标点，2s | official 原样 / 去标点，2s | 执行状态 |
| --- | --- | --- | --- |
| Nemotron EN 160ms | 1/5 / 1/5 | 0/5 / 0/5 | 两臂退出码均为 0 |
| Nemotron EN 560ms | 0/5 / 0/5 | 1/5 / 0/5 | 两臂退出码均为 0 |
| Nemotron 3.5 320ms | 0/5 / 0/4 | 0/5 / 0/4 | 两臂均只保存 9 条，退出码为 1 |
| Nemotron 3.5 560ms | 1/5 / 1/5 | 1/5 / 1/5 | 两臂退出码均为 0 |
| Kyutai 500ms | 5/5 / 2/5 | 5/5 / 3/5 | 两臂退出码均为 0 |

共保存 98 条结果，只有另外四个配置的 80 条属于正常完成的配对分片；不能宣称完整 100 条成功。320ms official 日志报 `Replay cleanup did not finish within 10 seconds`，未保存的末例不计作成功或普通未接话。已保存条目内部的 error/protocol_errors 为零，不代表分片正常退出。

official 已保存条目的 1,275 次请求全部完成审计，prompt mismatch 为零；其中正常退出分片为 1,050 次。EN 160ms 两条件合计 270 次、Kyutai 两条件合计 266 次均通过。审计通过只证明本轮 prompt 与官方规则一致，不证明各 ASR 的发布粒度和时钟与官方线上系统完全相同。

official 各条件延长至 12s 没有增加新回复；legacy EN 560ms 原样有一例在约 4.279s 启动。official Kyutai 原样五例正文启动约为 0.945、1.405、1.454、0.215、1.504s，尚未包含 TTS 与播放。official 多语言 560ms 两条件各有一个跨边界旧正文续写，未计为新的边界后回复。

主线两份 official `control/results.json` 的 SHA256：

- `official-nemotron_en-160`：`9e9f8480394144dfa30c28c7f2e0ebc8a40b792736aaf2df160635b915a8f676`。
- `official-kyutai-500`：`ef0c9a4b423f769cd8e63fba4dea48179a8b2b6cc7e3f35cbac60179b10cd656`。

结论：空白对齐没有解除 Nemotron EN 160ms 与官方控制权重的兼容问题；Kyutai 去标点由 5/5 降至 3/5，支持存在句读依赖，但不能证明全部跨 ASR 差异都由标点造成。后续路线分析见 [下一步建议](issue/README.md)。
