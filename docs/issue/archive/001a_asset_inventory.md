# Issue 001a：远端只读资产扫描

状态：完成，2026-10-18。父任务：001。范围仅为已指定文件的盘点，不包含许可审核、来源完整性认证或模型恢复。

交付 `scripts/remote/inventory_layer1_assets.py`、同路径说明、四项本地 conda 单元测试与远端实际扫描。run_id 为 `inventory-01`，远端目录 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-issue001-20261018/data/runs/inventory-01/`，退出码 0。仓库紧凑结果为 `reports/layer1_training/issue001-inventory-20261018/inventory_summary.json`，完整报告摘要 `c20806eb80134d4f082ded00c7354217dd694cdd030c948f4f184a322daca960`。

已记录官方代码、checkpoint、base、Nemotron 和 Kokoro 文件摘要及张量头；模型加载未执行。官方参考代码提交及 server.py 摘要符合历史冻结值。远端两仓库落后于本地且有未提交内容，不能直接作为新实验源码。Kokoro snapshot 缺少模型卡与许可副本，UltraChat 来源清单尚缺，交由父 issue 继续处理。实现提交在本轮维护提交中登记，以文件摘要定位实际扫描工具。
