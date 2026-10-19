# Issue 004a：恢复中断的 UltraChat 来源获取

状态：完成，已归档。日期：2026-10-19。父任务：[004](../004_training_data_and_annotation.md)。

远端实查：来源目录仅 train_0/1/2 完整文件，第 4 shard 为约 518MiB 的 train_3.jsonl.part；日志为 ChunkedEncodingError/IncompleteRead。旧 task-status.txt 是提交时快照，不作为实时排队证据。现有下载器遇断流直接退出，重启会从头写同一 partial。

- [x] 支持固定 URL 的 HTTP Range 续传，服务器忽略 Range 时安全重下当前 partial。
- [x] 有界重试、完整 SHA256 与大小核对；错误范围拒收，不信任 partial。
- [x] 对断流、Range、服务器退化和校验失败补4项测试及实现说明，本地通过。
- [x] 远端十个shard下载/验真完成，r4最终退出0；另以1CPU/512MiB硬限重新逐文件大小/SHA256复核，44.31秒、峰值19,656KiB、退出0。

恢复实现提交 `95e8853`。r1因同名wrapper覆盖入口失败，r2因pip清单采集失败，均未开始恢复；r3在容器创建期间撤销，现以独立入口/标准库依赖采集及已有镜像节点执行 `issue004-probe-recover-20261019-r4`。先验证代码及发布tokenizer，再继续原目录下载，不覆盖正式文件。新日志在 `data/runs/issue004-probe-recover-20261019-r4/source-recovery.log`，原始断流与失败日志保留。

最终结果：10/10文件完成，共9,288,990,895字节，complete=true。证据：[来源复核](../../../reports/layer1_training/issue016-source-and-exclusions-20261019/source_verification.json)。实现提交95e8853，下载run_id为issue004-probe-recover-20261019-r4，独立复核为issue016-source-verification-r1。数据生成/完整外部隔离与005/007仍待完成，不放行006。
