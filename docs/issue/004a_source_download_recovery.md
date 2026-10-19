# Issue 004a：恢复中断的 UltraChat 来源获取

状态：进行中。日期：2026-10-19。父任务：[004](004_training_data_and_annotation.md)。

远端实查：来源目录仅 train_0/1/2 完整文件，第 4 shard 为约 518MiB 的 train_3.jsonl.part；日志为 ChunkedEncodingError/IncompleteRead。旧 task-status.txt 是提交时快照，不作为实时排队证据。现有下载器遇断流直接退出，重启会从头写同一 partial。

- [ ] 支持固定 URL 的 HTTP Range 续传，服务器忽略 Range 时安全重下当前 partial。
- [ ] 有界重试、完整 SHA256 与大小核对；错误范围拒收，不信任 partial。
- [ ] 对断流、Range、服务器退化和校验失败补测试与实现说明。
- [ ] 远端重新下载与全部 shard 验真独立回填，未完成前不放行数据。
