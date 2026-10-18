# Layer 1 资产盘点测试

`tests/test_layer1_asset_inventory.py` 中的 `AssetInventoryTests` 使用临时目录和最小张量头检查完整文件哈希、参数形状、损坏头拒绝、空目录、断链、CLI 失败证据及拒绝覆盖。无模型、网络或 GPU 依赖。核心测试 `test_cli_retains_failure_and_refuses_overwrite` 验证缺失资产和无效 checkout 不会静默成功，并保留首次报告。

本地运行：`conda run -n paratalker-dev python -m unittest discover -s tests -p test_layer1_asset_inventory.py -v`。此测试不证明真实 checkpoint 完整恢复、模型 revision、许可或运行时对齐。
