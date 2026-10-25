# FDB跨集测试边界验证

对应 `tests/test_textturn_fdb.py`，只在本地已有conda CPU环境执行，不运行模型或集群测试。

`FdbContractTests`包含6项必要合同验证：Speak与start独立及真实返回等待；严格ASR边界前连续2／3周期和Listen打断；合并窗只算一次及缺失trace未知；无ASR／运行失败和未知分母；固定排序冻结、输入摘要和两臂静音长度；整次正式输出缺失仍保留100条未知。辅助`trace`只构造评分边界证据。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_textturn_fdb.py`。这些测试验证评分和输入合同，不替代远端真实ASR冒烟或模型质量评测。

输入冻结用例同时验证格式非法的候选摘要在写入清单前即被拒绝。
