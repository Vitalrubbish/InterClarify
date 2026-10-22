# X2Q-009：FLEURS 恢复与 X2-Turn 部署

状态：待实施。依赖：X2Q-008。[协议](../dev/X2-Turn/complete_test_on_fleurs.md)。

恢复固定 revision 的 100 test + 1 dev，哈希规则、时长与参考来源可追溯；远端独立 conda 安装冻结的 X2-Turn/vLLM overlay，导出模型并确认状态头与有效 delay。遵守单作业、GPU/内存/磁盘上限，不在登录节点运行模型。交付资产锁、环境锁和部署检查；实际测试属于 X2Q-011。
