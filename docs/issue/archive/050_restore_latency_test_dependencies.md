# Issue 050：恢复远端延迟测试依赖并重提任务

状态：完成，2026-10-21，已归档。用户说明可能误删远端拷贝源码，要求检查并重提。

## 检查结论与恢复范围

延迟测试 r1 源码包及224个文件摘要完整，原任务 job-179251430615923992781-xuan-zhang 尚未启动、仍在排队。发现最终候选加载器引用的训练资产清单缺失：`interclarify-layer1-training-20261019/source/91b7eb2/reports/layer1_training/issue001-inventory-20261018/inventory_summary.json`。checkpoint、训练manifest/summary/权重指纹及现役conda仍存在。

从本地Git提交91b7eb2恢复清单原文，SHA256为`ca93ed2e34df36acf9bce1ee8be869f78f0105a18a7e9cbfd10f7fcda0d7b424`，与训练manifest登记的inventory_sha256一致。仅恢复现役加载依赖，不恢复已退役的全部实现或修改原训练身份。

- [x] 核查当前测试源码、任务状态和加载器的实际依赖。
- [x] 取消旧排队任务，避免重复占用资源；保留旧提交脚本和日志。
- [x] 恢复清单，摘要与训练记录一致；40个加载依赖文件存在性与大小通过，现役conda入口存在。
- [x] 独立r2快照224个文件摘要通过，重提任务 `job-179251495575111326759-xuan-zhang`。

恢复和重提完成并归档；[r2记录](../../../reports/latency/20261021-r2/README.md)保留路径与身份，047/048/049的远端验证继续跟踪，不将任务提交等同于测试通过。
