# 官方 Word 比较器测试

`RuntimeComparisonTests` 覆盖首次差异定位、无请求/历史缺失拒绝、参考源码摘要检查，以及 Word 清单对错误类型、乱序、越界时间和重复样本的拒绝。通过固定官方 AST 的 CPU 回放检查逐词 strip、同拍空格连接和空拍，不使用完整转写伪造在线到达时间。

测试只核验比较器与输入契约，合成夹具明确标记为测试数据；真实五例权重自由回放和集成生命周期在远端 conda 环境另验。运行 `conda run -n paratalker-dev python -m unittest discover -s tests -p test_layer1_runtime_comparison.py`。

设置 `DUPLEX_OFFICIAL_SOURCE` 时执行固定官方 AST 的 CPU 回放；设置 `DUPLEX_XTALK_LIFECYCLE=1` 时在远端客户端 conda 中执行真实 EventBus/Assembler/RuntimeAdapter 的在途关闭、取消和新会话隔离检查。关闭旧实例后新建会话，不新增产品 reset 接口；旧会话已产生的可听事实不能撤销，检查只要求取消后无新增提交及新历史不混入旧内容。
